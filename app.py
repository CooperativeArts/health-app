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
        input[type="text"] { width: 80%; padding: 10px; }
        button { padding: 10px 20px; background-color: #007bff; color: white; border: none; cursor: pointer; }
        button:disabled { background-color: #ccc; }
        .loading { color: #666; }
        .error { color: red; }
        .source { color: #666; font-size: 0.9em; margin-top: 5px; }
    </style>
</head>
<body>
    <h1>Compliance and Risk Assistant</h1>
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
            const submitBtn = document.getElementById('submit-btn');
            
            submitBtn.disabled = true;
            chatBox.innerHTML += '<p><b>Q:</b> ' + question + '</p>';
            chatBox.innerHTML += '<p class="loading">Loading...</p>';
            chatBox.scrollTop = chatBox.scrollHeight;
            
            try {
                const response = await fetch('/query?q=' + encodeURIComponent(question));
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
        
        # Build context string
        context_text = ""
        total_chars = 0
        max_chars = 20000
        
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
        
        # Prepare system prompt based on found entities
        system_prompt = """You are a Compliance and Risk Assistant analyzing documents from different contexts:
- Policy Documents: Official policies and frameworks
- Operational Guidelines: Practical procedures and forms
- Case Files: Client-specific information and assessments

Important guidelines:
1. Always specify which type of document and page contains your information
2. When answering operational questions, reference both policies and procedures
3. For case-specific questions, connect client information with relevant policies
4. Quote relevant text when appropriate
5. If information seems missing, mention what should be checked
6. Focus on compliance and risk management
7. When names are mentioned, clarify their role (e.g., client, worker, family member)
8. For visits, always check both operational guidelines and client-specific requirements"""

        # Add context about found entities
        if search_context['entities']:
            system_prompt += "\n\nRelevant entities in question:"
            for entity_type, values in search_context['entities'].items():
                if values:
                    system_prompt += f"\n- {entity_type}: {', '.join(values)}"
        
        # Analyze with GPT-4
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"""Question: {user_question}

Here are relevant sections from multiple documents:

{context_text}

Provide a detailed answer that synthesizes information from all relevant sources. Consider policy requirements, operational procedures, and any case-specific details. If this involves a visit or client interaction, be sure to highlight safety and procedural requirements."""}
            ],
            temperature=0,
            request_timeout=30
        )
        
        answer = response.choices[0].message['content']
        
        # Add coverage info
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