from flask import Flask, request, render_template_string
import openai
import os
from dotenv import load_dotenv
import json
from collections import defaultdict
import re
from typing import List, Dict, Any
from dataclasses import dataclass
from pathlib import Path

app = Flask(__name__)

@dataclass
class DocumentSection:
    content: str
    page: int
    context: str
    document_path: str
    document_name: str
    relevance_score: float
    entities: Dict[str, List[str]]

class EntityExtractor:
    def __init__(self):
        self.person_indicators = ['mother', 'father', 'child', 'worker', 'carer', 'guardian']
        self.family_indicators = ['family', 'household', 'home', 'family\'s']
        self.name_pattern = r'(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)'
    
    def extract_entities(self, text: str) -> Dict[str, List[str]]:
        entities = defaultdict(set)
        
        # Extract family names
        for indicator in self.family_indicators:
            patterns = [
                f"({self.name_pattern})\\s+{indicator}",
                f"{indicator}\\s+({self.name_pattern})"
            ]
            for pattern in patterns:
                matches = re.finditer(pattern, text, re.IGNORECASE)
                for match in matches:
                    family_name = match.group(1)
                    entities['family_names'].add(family_name)
                    entities['names'].add(family_name)
        
        # Extract names with roles
        for indicator in self.person_indicators:
            pattern = f"(?:{indicator}|{indicator.capitalize()})\\s+({self.name_pattern})"
            matches = re.finditer(pattern, text)
            for match in matches:
                name = match.group(1)
                entities[indicator].add(name)
                entities['names'].add(name)
        
        # Extract standalone names
        standalone_names = re.finditer(f"\\b{self.name_pattern}\\b", text)
        for match in standalone_names:
            name = match.group(0)
            if any(name in roles for roles in entities.values()):
                continue
            entities['names'].add(name)
        
        # Extract client IDs
        client_ids = re.finditer(r'client[_\s]*(\d+)', text.lower())
        for match in client_ids:
            entities['client_ids'].add(match.group(1))
            
        return {k: list(v) for k, v in entities.items()}

class DocumentManager:
    def __init__(self):
        self.entity_extractor = EntityExtractor()
        self.document_cache = {}
        self.required_documents = self._load_document_requirements()
    
    def _load_document_requirements(self) -> Dict[str, Dict[str, Any]]:
        """Load required documents from operational guidelines"""
        base_requirements = {
            'consent': {
                'keywords': ['consent form', 'consent document', 'signed consent', 'client consent'],
                'mandatory': True,
                'found_in': None,
                'description': 'Client consent form'
            },
            'privacy': {
                'keywords': ['privacy form', 'privacy statement', 'privacy acknowledgment', 'privacy consent'],
                'mandatory': True,
                'found_in': None,
                'description': 'Privacy statement and acknowledgment'
            },
            'intake': {
                'keywords': ['intake form', 'intake assessment', 'initial assessment', 'intake.pdf', 'intake_form'],
                'mandatory': True,
                'found_in': None,
                'description': 'Client intake form'
            },
            'rights': {
                'keywords': ['rights and responsibilities', 'client rights', 'responsibilities form', 'rights form'],
                'mandatory': False,
                'found_in': None,
                'description': 'Rights and responsibilities acknowledgment'
            },
            'risk_assessment': {
                'keywords': ['risk assessment', 'risk matrix', 'safety assessment', 'risk_assessment', 'best_interest'],
                'mandatory': True,
                'found_in': None,
                'description': 'Safety and risk assessment'
            }
        }
        
        try:
            # Search operational guidelines for document requirements
            op_guidelines_path = Path('operational_docs/operational_guidelines')
            if op_guidelines_path.exists():
                for file_path in op_guidelines_path.rglob('*.pdf'):
                    if 'privacy' in file_path.name.lower() or 'consent' in file_path.name.lower():
                        from pypdf import PdfReader
                        reader = PdfReader(str(file_path))
                        for page in reader.pages:
                            text = page.extract_text().lower()
                            # Look for sections describing required documents
                            if 'required document' in text or 'mandatory form' in text:
                                # Parse requirements and update base_requirements
                                # [Add detailed parsing logic here based on your guidelines format]
                                pass
        except Exception as e:
            print(f"Error loading document requirements: {str(e)}")
        
        return base_requirements

    def check_missing_documents(self, all_content: List[DocumentSection]) -> Dict[str, Dict[str, Any]]:
        document_status = {}
        
        # Check each required document
        for doc_type, details in self.required_documents.items():
            status = {
                'found': False,
                'mandatory': details['mandatory'],
                'description': details['description'],
                'found_in': None
            }
            
            # Check content for keywords
            for section in all_content:
                content_lower = section.content.lower()
                if any(keyword in content_lower for keyword in details['keywords']):
                    status['found'] = True
                    status['found_in'] = section.document_name
                    break
            
            document_status[doc_type] = status
        
        return document_status
        
    def get_document_type(self, path: Path) -> str:
        if 'docs' == path.parent.name:
            return "Policy"
        elif 'operational_docs' in path.parts:
            if 'forms' in path.parts:
                return "Forms"
            elif 'operational_guidelines' in path.parts:
                return "Operational Guidelines"
            return "Operational"
        elif 'case_docs' in path.parts:
            return "Case Files"
        return "Unknown"
    
    def scan_document(self, file_path: Path, search_context: Dict[str, Any]) -> List[DocumentSection]:
        try:
            # Use cache if available
            if str(file_path) in self.document_cache:
                content = self.document_cache[str(file_path)]
            else:
                from pypdf import PdfReader
                reader = PdfReader(str(file_path))
                content = []
                for page_num, page in enumerate(reader.pages):
                    text = page.extract_text()
                    if text.strip():
                        content.append((page_num + 1, text))
                self.document_cache[str(file_path)] = content

            doc_type = self.get_document_type(file_path)
            sections = []
            
            for page_num, text in content:
                # Extract entities from the text
                entities = self.entity_extractor.extract_entities(text)

	        # Print what we find for debugging
                if 'alias' in text.lower():  # Debug check
                    print(f"Found 'alias' in {file_path}")
                    print(f"Entities found: {entities}")
                
                # Calculate relevance score based on multiple factors
                score = self._calculate_relevance(
                    text=text,
                    search_terms=search_context['terms'],
                    entities=entities,
                    search_entities=search_context['entities'],
                    doc_type=doc_type
                )
                
                if score > 0:
                    sections.append(DocumentSection(
                        content=text,
                        page=page_num,
                        context=doc_type,
                        document_path=str(file_path),
                        document_name=file_path.name,
                        relevance_score=score,
                        entities=entities
                    ))
            
            return sections
            
        except Exception as e:
            print(f"Error reading {file_path}: {str(e)}")
            return []
    
    def _calculate_relevance(self, text: str, search_terms: List[str], 
                           entities: Dict[str, List[str]], 
                           search_entities: Dict[str, List[str]],
                           doc_type: str) -> float:
        score = 0.0
        
        # Term matching (case insensitive)
        text_lower = text.lower()
        term_matches = sum(term.lower() in text_lower for term in search_terms)
        score += term_matches * 1.0
        
        # Entity matching (weighted higher and case insensitive)
        for entity_type, search_names in search_entities.items():
            for name in search_names:
                name_lower = name.lower()
                # Higher weight for exact family name matches
                if entity_type == 'family_names' and name_lower in text_lower:
                    score += 5.0  # Increased from 3.0 to give higher priority
                    # Extra boost for exact matches
                    if f"{name_lower} family" in text_lower or f"family {name_lower}" in text_lower:
                        score += 3.0
                    # Extra boost if name appears near case-related terms
                    if any(term in text_lower[max(0, text_lower.find(name_lower)-50):
                                           min(len(text_lower), text_lower.find(name_lower)+50)] 
                           for term in ['client', 'case', 'family', 'mother', 'father', 'child']):
                        score += 2.0
                elif name_lower in text_lower:
                    score += 2.0
                    
        # Boost case files even higher for family queries
        if doc_type == "Case Files":
            score += 2.5  # Increased from 1.5

        # Context boost for risk-related content
        if any(term in text_lower for term in ['risk', 'hazard', 'danger', 'safety', 'warning', 'incident']):
            score += 2.0
            
        # Boost for operational documents when searching for procedures
        if doc_type in ["Operational Guidelines", "Forms"] and \
           any(term in ['procedure', 'form', 'guide', 'visit'] for term in search_terms):
            score += 1.5
            
        return score

class QueryProcessor:
    def __init__(self):
        self.entity_extractor = EntityExtractor()
    
    def process_question(self, question: str) -> Dict[str, Any]:
        # Extract entities from the question
        entities = self.entity_extractor.extract_entities(question)
        
        # Extract search terms (excluding found entities and common words)
        common_words = {'what', 'is', 'are', 'in', 'the', 'and', 'or', 'to', 'a', 'an', 
                       'about', 'how', 'can', 'do', 'does', 'visiting', 'need', 'know',
                       'when', 'risks', 'risk'}
        
        # Add domain-specific terms
        terms = set()
        for word in question.lower().split():
            word = word.strip('?.,!')
            if word not in common_words and \
               not any(word in str(e).lower() for e in entities.values()):
                terms.add(word)
        
        # Add context-specific terms
        if 'risk' in question.lower() or 'risks' in question.lower():
            terms.update(['risk', 'hazard', 'safety', 'danger', 'incident'])
        if 'visit' in question.lower():
            terms.update(['visit', 'assessment', 'safety', 'procedure'])
        
        return {
            'terms': list(terms),
            'entities': entities
        }

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>CARA</title>
    <style>
        body { max-width: 800px; margin: auto; padding: 20px; font-family: Arial, sans-serif; }
        #chat-box { height: 400px; border: 1px solid #ccc; overflow-y: scroll; margin: 20px 0; padding: 10px; }
        .controls { margin-bottom: 20px; }
        .response-type { margin-bottom: 10px; }
        .response-type label { 
            display: inline-block;
            padding: 8px 16px;
            margin-right: 10px;
            background-color: #f0f0f0;
            border: 1px solid #ccc;
            border-radius: 4px;
            cursor: pointer;
        }
        .response-type input[type="radio"]:checked + label {
            background-color: #007bff;
            color: white;
            border-color: #0056b3;
        }
        .response-type input[type="radio"] { display: none; }
        .detail-level { margin-bottom: 10px; }
        select { 
            padding: 8px;
            margin-left: 10px;
            border-radius: 4px;
            border: 1px solid #ccc;
        }
        input[type="text"] { 
            width: 80%; 
            padding: 10px;
            border: 1px solid #ccc;
            border-radius: 4px;
        }
        button { 
            padding: 10px 20px; 
            background-color: #007bff; 
            color: white; 
            border: none;
            border-radius: 4px;
            cursor: pointer; 
        }
        button:disabled { background-color: #ccc; }
        .loading { color: #666; }
        .error { color: red; }
    </style>
</head>
<body>
    <h1>Compliance and Risk Assistant</h1>
    <div class="controls">
        <div class="response-type">
            <input type="radio" id="risk" name="type" value="risk" checked>
            <label for="risk">Risk Assessment</label>
            
            <input type="radio" id="operational" name="type" value="operational">
            <label for="operational">Operational Requirements</label>
            
            <input type="radio" id="family" name="type" value="family">
            <label for="family">Family Information</label>
        </div>
        <div class="detail-level">
            <label>Detail Level:</label>
            <select id="detail-level">
                <option value="concise">Concise</option>
                <option value="detailed">Detailed</option>
            </select>
        </div>
    </div>
    <div id="chat-box"></div>
    <form id="chat-form">
        <input type="text" id="question" placeholder="Ask a question..." required>
        <button type="submit" id="submit-btn">Send</button>
    </form>
    <script>
        document.getElementById('chat-form').onsubmit = async function(e) {
            e.preventDefault();
            const chatBox = document.getElementById('chat-box');
            const question = document.getElementById('question').value;
            const type = document.querySelector('input[name="type"]:checked').value;
            const detail = document.getElementById('detail-level').value;
            const submitBtn = document.getElementById('submit-btn');
            
            submitBtn.disabled = true;
            chatBox.innerHTML += '<p><b>Q:</b> ' + question + '</p>';
            chatBox.innerHTML += '<p class="loading">Loading...</p>';
            chatBox.scrollTop = chatBox.scrollHeight;
            
            try {
                const response = await fetch('/query?q=' + encodeURIComponent(question) + 
                                          '&type=' + type + '&detail=' + detail);
                const answer = await response.text();
                chatBox.removeChild(chatBox.lastChild);
                chatBox.innerHTML += '<p><b>A:</b> ' + answer + '</p>';
            } catch (error) {
                chatBox.removeChild(chatBox.lastChild);
                chatBox.innerHTML += '<p class="error"><b>Error:</b> ' + error.message + '</p>';
            } finally {
                submitBtn.disabled = false;
                document.getElementById('question').value = '';
                chatBox.scrollTop = chatBox.scrollHeight;
            }
        };
    </script>
</body>
</html>
'''

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/query')
def query():
    try:
        load_dotenv()
        openai.api_key = os.getenv('OPENAI_API_KEY')
        user_question = request.args.get('q', '')
        response_type = request.args.get('type', 'risk')
        detail_level = request.args.get('detail', 'concise')
        
        # Initialize components
        query_processor = QueryProcessor()
        doc_manager = DocumentManager()
        
        # Process the question
        search_context = query_processor.process_question(user_question)
        print(f"Detected entities: {search_context['entities']}")  # Add this debug line here
        
        # Determine which folders to search
        folders_to_search = ['docs', 'operational_docs']
        if search_context['entities'].get('client_ids') or search_context['entities'].get('names'):
            folders_to_search.append('case_docs')
        
        # Collect relevant content
        all_content = []
        
        for folder in folders_to_search:
            folder_path = Path(folder)
            if folder_path.exists():
                for file_path in folder_path.rglob('*.pdf'):
                    sections = doc_manager.scan_document(file_path, search_context)
                    all_content.extend(sections)
        
        # Add these debug lines here
        print(f"Found {len(all_content)} relevant sections")
        for item in all_content:
            print(f"Document: {item.document_name}, Score: {item.relevance_score}")
        
        # Sort by relevance score
        all_content.sort(key=lambda x: x.relevance_score, reverse=True)
        
        # Check for missing documents
        missing_docs = doc_manager.check_missing_documents(all_content)
        
        # Build context text
        context_text = ""
        total_chars = 0
        max_chars = 5000 if detail_level == 'detailed' else 2000  # Reduced from 10000
        
        # Add missing documents to context for operational queries
        if response_type == 'operational':
            missing_list = [doc_type.replace('_', ' ').title() for doc_type, found in missing_docs.items() 
                          if not found]
            if missing_list:
                context_text = "MISSING REQUIRED DOCUMENTS:\n- " + "\n- ".join(missing_list) + "\n\n"
        
        # Add document content to context
        for item in all_content:
            section = f"\n=== From {item.context}: {item.document_name}, Page {item.page} ===\n"
            section += f"[Entities found: {', '.join([f'{k}: {v}' for k, v in item.entities.items() if v])}]\n"
            section += f"{item.content}\n"
            
            if total_chars + len(section) <= max_chars:
                context_text += section
                total_chars += len(section)
            else:
                break
        
        if not context_text.strip():
            return ("I couldn't find relevant information in the documents. "
                   "Please try rephrasing your question or providing more context.")

        # Define system prompts for each type and detail level
        system_prompts = {
            'risk': {
                'concise': """You are a Risk Assessment Assistant. Focus on:
1. The most critical family-specific risks (maximum 3-4 points)
2. The most crucial safety requirements for those specific risks
3. Be direct and specific - no generic advice
4. Keep each risk/requirement to one line
5. Total response should be no more than 6-8 lines

Remember: Focus on the most urgent and serious risks specific to this family.""",

                'detailed': """You are a Risk Assessment Assistant analyzing safety concerns:
1. List ALL identified risks from the documents
2. Categorize risks (e.g., immediate safety, long-term, environmental)
3. For each risk, provide:
   - Source of information (document and page)
   - Context and severity
   - Recommended mitigation strategies
4. Connect risks to relevant policies and procedures
5. Identify any gaps in risk assessment"""
            },
            'operational': {
                'concise': """You are an Operational Compliance Assistant. Your primary focus is on missing or incomplete documentation.

1. FIRST check for required documents:
   - Consent Form (mandatory)
   - Privacy Form (mandatory)
   - Rights and Responsibilities Form
   - Risk Assessment
   - Intake Form
2. List ANY missing required documents first
3. Then list critical procedural requirements
4. Keep each point to one line

Remember: Always state explicitly which required documents are missing.""",

                'detailed': """You are an Operational Compliance Assistant reviewing requirements:
1. First and foremost, check for required documentation:
   - Consent Form (mandatory)
   - Privacy Form (mandatory)
   - Rights and Responsibilities Form
   - Risk Assessment
   - Intake Form
2. Explicitly state which required documents are missing or not found
3. Quote relevant sections from operational guidelines about required documentation
4. Detail consequences of missing documentation
5. Provide step-by-step guidance for obtaining missing documents
6. List any other compliance gaps
7. Reference specific policies and procedures"""
            },
            'family': {
                'concise': """You are a Family Information Assistant. Follow these rules strictly:
1. ONLY provide information that is explicitly about the named family/person
2. Do not include any quotes or information unless they are specifically from/about the named person
3. If you see names that don't match the request, exclude that information entirely
4. If unsure if information belongs to this family, omit it
5. Keep each point to one line
6. Maximum 6-8 lines total

Remember: Better to provide less information than to mix up different families.""",

                'detailed': """You are a Family Information Assistant. Follow these rules strictly:
1. ONLY provide information from documents that explicitly name this specific family
2. Cross-reference every piece of information to ensure it's about the correct family
3. Never mix quotes or information from different families
4. If a document mentions other names, completely exclude that section
5. Organize confirmed information into:
   - Family composition (only if explicitly stated)
   - Current situation (only if clearly about this family)
   - Key concerns (must be specifically linked to this family)
   - Available services (must be currently engaged with this family)
6. If you're not 100% certain information belongs to this family, exclude it
7. Note any gaps in information rather than filling in with uncertain details

Remember: Accuracy is more important than completeness. Never combine information from different families."""
            }
        }

        # Get appropriate system prompt
        system_prompt = system_prompts[response_type][detail_level]

        # Add entity context if entities are found
        if search_context['entities']:
            system_prompt += "\n\nRelevant entities in question:"
            for entity_type, values in search_context['entities'].items():
                if values:
                    system_prompt += f"\n- {entity_type}: {', '.join(values)}"

        # Build appropriate user prompt
        user_prompt = f"""Question: {user_question}

Here are relevant sections from documents:

{context_text}

Provide a {detail_level} response focusing on {response_type} aspects."""

        # Increase GPT timeout:
        response = openai.ChatCompletion.create(
    model="gpt-4",
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ],
    temperature=0,
    request_timeout=45  # Increased from 30
)
        
        answer = response.choices[0].message['content']
        
        # Add minimal coverage info for concise mode
        if detail_level == 'concise':
            coverage_info = "\n\nBased on relevant policy and operational documents."
        else:
            coverage_info = (f"\n\nDocument Coverage: Searched {len(list(Path('docs').glob('*.pdf')))} policy documents, "
                           f"{len(list(Path('operational_docs').rglob('*.pdf')))} operational documents")
            if 'case_docs' in folders_to_search:
                coverage_info += f", and relevant case files"
            coverage_info += f". Found relevant content in {len(set(item.document_name for item in all_content))} documents."
        
        return answer + coverage_info
        
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8000)