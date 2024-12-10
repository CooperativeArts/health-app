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
        self.family_indicators = ['family', 'household', 'home']
        self.name_pattern = r'(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)'
    
    def extract_entities(self, text: str) -> Dict[str, List[str]]:
        entities = defaultdict(set)
        
        # Extract family names
        for indicator in self.family_indicators:
            # Match patterns like "Alias family" or "family Alias"
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
        
        # Extract names with roles (existing code)
        for indicator in self.person_indicators:
            pattern = f"(?:{indicator}|{indicator.capitalize()})\\s+({self.name_pattern})"
            matches = re.finditer(pattern, text)
            for match in matches:
                name = match.group(1)
                entities[indicator].add(name)
                entities['names'].add(name)
        
        # Extract standalone names (existing code)
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
                name_lower = name.lower()
                # Higher weight for exact family name matches
                if entity_type == 'family_names' and name_lower in text.lower():
                    score += 3.0  # Highest priority for family matches
                elif name_lower in text.lower():
                    score += 2.0
                    
                # Additional boost for case files
                if doc_type == "Case Files":
                    score += 1.5
        
        # Context boost for risk-related content
        if any(term in text.lower() for term in ['risk', 'hazard', 'danger', 'safety', 'warning', 'incident']):
            score += 2.0
            
        # Boost for operational documents when searching for procedures
        if doc_type in ["Operational Guidelines", "Forms"] and \
           any(term in ['procedure', 'form', 'guide', 'visit'] for term in search_terms):
            score += 1.5
            
        return score

class QueryProcessor:
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
        .mode-toggle { margin-bottom: 10px; }
        .mode-toggle label { margin-right: 15px; }
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
    <div class="mode-toggle">
        <label>
            <input type="radio" name="mode" value="quick" checked> Quick Response
        </label>
        <label>
            <input type="radio" name="mode" value="detailed"> Detailed Response
        </label>
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
            const mode = document.querySelector('input[name="mode"]:checked').value;
            const submitBtn = document.getElementById('submit-btn');
            
            submitBtn.disabled = true;
            chatBox.innerHTML += '<p><b>Q:</b> ' + question + '</p>';
            chatBox.innerHTML += '<p class="loading">Loading...</p>';
            chatBox.scrollTop = chatBox.scrollHeight;
            
            try {
                const response = await fetch('/query?q=' + encodeURIComponent(question) + '&mode=' + mode);
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
        response_mode = request.args.get('mode', 'quick')
        
        # Initialize components
        query_processor = QueryProcessor()
        doc_manager = DocumentManager('.')
        
        # Process the question - moved up
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
        
        # Build context text
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
        
        # Adjust system prompt based on response mode
        system_prompt_quick = """You are a Compliance and Risk Assistant providing quick, essential guidance. Focus on:
1. Immediate actions needed
2. Key safety requirements
3. Critical procedural steps
4. Essential policy points

Keep responses concise and action-oriented. Only reference specific documents if crucial."""

        system_prompt_detailed = """You are a Compliance and Risk Assistant analyzing documents from different contexts:
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

        # Choose appropriate system prompt
        system_prompt = system_prompt_quick if response_mode == 'quick' else system_prompt_detailed
        
        # Add entity context if in detailed mode or if safety-critical entities found
        if response_mode == 'detailed' or any(
            entity_type in search_context['entities'] 
            for entity_type in ['client_ids', 'child', 'mother', 'father']
        ):
            system_prompt += "\n\nRelevant entities in question:"
            for entity_type, values in search_context['entities'].items():
                if values:
                    system_prompt += f"\n- {entity_type}: {', '.join(values)}"

        # Modify user prompt based on mode
        user_prompt_quick = f"""Question: {user_question}

Provide only the essential information needed for immediate action. Focus on safety, required steps, and critical policies."""

        user_prompt_detailed = f"""Question: {user_question}

Here are relevant sections from multiple documents:

{context_text}

Provide a detailed answer that synthesizes information from all relevant sources. Consider policy requirements, operational procedures, and any case-specific details. If this involves a visit or client interaction, be sure to highlight safety and procedural requirements."""

        # Analyze with GPT-4
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt_quick if response_mode == 'quick' else user_prompt_detailed}
            ],
            temperature=0,
            request_timeout=30
        )
        
        answer = response.choices[0].message['content']
        
        # Add minimal coverage info for quick mode
        if response_mode == 'quick':
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