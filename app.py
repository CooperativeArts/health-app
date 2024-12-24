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
        self.name_pattern = r'(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)'
    
    def extract_entities(self, text: str) -> Dict[str, List[str]]:
        entities = defaultdict(set)
        
        # Extract names with roles
        for indicator in self.person_indicators:
            pattern = f"(?:{indicator}|{indicator.capitalize()})\\s+({self.name_pattern})"
            matches = re.finditer(pattern, text)
            for match in matches:
                name = match.group(1)
                entities[indicator].add(name)
                entities['names'].add(name)
        
        # Extract standalone names (likely mentioned without roles)
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
    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        self.entity_extractor = EntityExtractor()
        self.document_cache = {}
        self.required_documents = {
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
                'keywords': ['intake form', 'intake assessment', 'initial assessment', 'intake_form'],
                'mandatory': True,
                'found_in': None,
                'description': 'Client intake form'
            },
            'rights': {
                'keywords': ['rights and responsibilities', 'client rights', 'responsibilities form'],
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
        
        # Term matching
        term_matches = sum(term.lower() in text.lower() for term in search_terms)
        score += term_matches * 1.0
        
        # Entity matching (weighted higher)
        for entity_type, search_names in search_entities.items():
            for name in search_names:
                if name.lower() in text.lower():
                    score += 2.0  # Weight entity matches higher
                    # Additional boost for case files when matching names
                    if doc_type == "Case Files":
                        score += 1.0
        
        # Context boost for operational documents when searching for procedures
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
                       'about', 'how', 'can', 'do', 'does', 'visiting', 'need', 'know'}
        
        # Add domain-specific terms
        terms = set()
        for word in question.lower().split():
            word = word.strip('?.,!')
            if word not in common_words and \
               not any(word in str(e).lower() for e in entities.values()):
                terms.add(word)
        
        # Add context-specific terms based on question type
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
    <div class="detail-level">
        <label>Detail Level:</label>
        <select id="detail-level">
            <option value="concise">Concise</option>
            <option value="detailed">Detailed</option>
        </select>
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
            const detail = document.getElementById('detail-level').value;
            const submitBtn = document.getElementById('submit-btn');
            
            submitBtn.disabled = true;
            chatBox.innerHTML += '<p><b>Q:</b> ' + question + '</p>';
            chatBox.innerHTML += '<p class="loading">Loading...</p>';
            chatBox.scrollTop = chatBox.scrollHeight;
            
            try {
                const response = await fetch('/query?q=' + encodeURIComponent(question) + 
                                          '&detail=' + detail);
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
        detail_level = request.args.get('detail', 'concise')
        
        # Initialize components
        query_processor = QueryProcessor()
        doc_manager = DocumentManager('.')
        
        # Process the question
        search_context = query_processor.process_question(user_question)
        
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
        
        # Sort by relevance score
        all_content.sort(key=lambda x: x.relevance_score, reverse=True)
        
        # Check for missing documents
        missing_docs = doc_manager.check_missing_documents(all_content)
        
        # Build context text
        context_text = ""
        total_chars = 0
        max_chars = 20000 if detail_level == 'detailed' else 2000
        
        # Add missing documents info to context
        missing_list = [f"{details['description']} (mandatory)" if details['mandatory'] else details['description']
                       for doc_type, details in missing_docs.items() if not details['found']]
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
        
        system_prompt = """You are a Compliance and Risk Assistant. Your role is to analyze documents and provide clear, actionable advice.

In CONCISE mode (default):
1. Start with missing required documents (if any)
2. Give only the most crucial information in bullet points
3. Keep it to 4-5 bullet points maximum
4. Each point should be one line

In DETAILED mode:
1. List ALL missing required documents with explanations
2. Provide comprehensive analysis with document references
3. Include relevant quotes from documents
4. Note any gaps or inconsistencies
5. Recommend next steps

Always prioritize:
1. Required document status
2. Safety requirements
3. Compliance with procedures
4. Family-specific information"""

        # Add context about found entities
        if search_context['entities']:
            system_prompt += "\n\nRelevant entities in question:"
	   for entity_type, values in search_context['entities'].items():
                if values:
                    system_prompt += f"\n- {entity_type}: {', '.join(values)}"
        
        # Build user prompt
        user_prompt = f"""Question: {user_question}

Here are relevant sections from documents:

{context_text}

Provide a {detail_level} response following the guidelines."""

        # Analyze with GPT-4
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0,
            request_timeout=30
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