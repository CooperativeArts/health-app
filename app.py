from flask import Flask, request, render_template_string
import openai
import os
from dotenv import load_dotenv
import json
from collections import defaultdict
import re
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
from pathlib import Path
import pkg_resources

class DocumentReader:
    """Factory class to handle different document types"""
    
    @staticmethod
    def create_reader(file_path: Path) -> 'BaseDocumentReader':
        extension = file_path.suffix.lower()
        if extension == '.pdf':
            return PDFReader()
        elif extension in ['.doc', '.docx']:
            return WordReader()
        elif extension in ['.xls', '.xlsx']:
            return ExcelReader()
        elif extension == '.html':
            return HTMLReader()
        elif extension == '.txt':
            return TextReader()
        elif extension in ['.md', '.markdown']:
            return MarkdownReader()
        else:
            raise ValueError(f"Unsupported file type: {extension}")

class BaseDocumentReader:
    def read(self, file_path: Path) -> List[Tuple[int, str]]:
        """Return list of (page_number, content) tuples"""
        raise NotImplementedError

class PDFReader(BaseDocumentReader):
    def read(self, file_path: Path) -> List[Tuple[int, str]]:
        from pypdf import PdfReader
        reader = PdfReader(str(file_path))
        content = []
        for page_num, page in enumerate(reader.pages):
            text = page.extract_text()
            if text.strip():
                content.append((page_num + 1, text))
        return content

class WordReader(BaseDocumentReader):
    def read(self, file_path: Path) -> List[Tuple[int, str]]:
        import docx2txt  # for .docx
        from subprocess import run, PIPE  # for .doc (using antiword)
        
        if file_path.suffix.lower() == '.docx':
            text = docx2txt.process(str(file_path))
            return [(1, text)] if text.strip() else []
        else:  # .doc
            try:
                result = run(['antiword', str(file_path)], stdout=PIPE, stderr=PIPE)
                text = result.stdout.decode('utf-8')
                return [(1, text)] if text.strip() else []
            except FileNotFoundError:
                # Fallback to textract if antiword isn't available
                import textract
                text = textract.process(str(file_path)).decode('utf-8')
                return [(1, text)] if text.strip() else []

class ExcelReader(BaseDocumentReader):
    def read(self, file_path: Path) -> List[Tuple[int, str]]:
        import pandas as pd
        
        content = []
        try:
            # Read all sheets
            xlsx = pd.ExcelFile(str(file_path))
            for sheet_num, sheet_name in enumerate(xlsx.sheet_names):
                df = pd.read_excel(xlsx, sheet_name)
                # Convert dataframe to string representation
                text = f"Sheet: {sheet_name}\n{df.to_string()}"
                content.append((sheet_num + 1, text))
        except Exception as e:
            print(f"Error reading Excel file {file_path}: {str(e)}")
        return content

class HTMLReader(BaseDocumentReader):
    def read(self, file_path: Path) -> List[Tuple[int, str]]:
        from bs4 import BeautifulSoup
        
        with open(file_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f.read(), 'html.parser')
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            # Get text
            text = soup.get_text(separator='\n')
            return [(1, text)] if text.strip() else []

class TextReader(BaseDocumentReader):
    def read(self, file_path: Path) -> List[Tuple[int, str]]:
        with open(file_path, 'r', encoding='utf-8') as f:
            text = f.read()
            return [(1, text)] if text.strip() else []

class MarkdownReader(BaseDocumentReader):
    def read(self, file_path: Path) -> List[Tuple[int, str]]:
        import markdown
        
        with open(file_path, 'r', encoding='utf-8') as f:
            md_text = f.read()
            # Convert to HTML first
            html = markdown.markdown(md_text)
            # Use BeautifulSoup to extract text
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            text = soup.get_text(separator='\n')
            return [(1, text)] if text.strip() else []

app = Flask(__name__)

def check_dependencies():
    required_packages = [
        'flask', 'openai', 'python-dotenv', 'pypdf',
        'docx2txt', 'pandas', 'openpyxl', 'beautifulsoup4',
        'markdown', 'textract'
    ]
    installed = {pkg.key for pkg in pkg_resources.working_set}
    missing = [pkg for pkg in required_packages if pkg not in installed]
    if missing:
        raise ModuleNotFoundError(f"Missing required packages: {', '.join(missing)}")

def validate_environment():
    required_vars = ['OPENAI_API_KEY']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")

def validate_directories():
    required_dirs = ['docs', 'operational_docs', 'case_docs']
    for dir_name in required_dirs:
        dir_path = Path(dir_name)
        if not dir_path.exists():
            dir_path.mkdir(parents=True, exist_ok=True)

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
                # Create appropriate reader for file type
                reader = DocumentReader.create_reader(file_path)
                content = reader.read(file_path)
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
        text_lower = text.lower()
        
        # Term matching with weighted importance
        term_weights = {
            # Permission terms (highest priority)
            'permission': 4.0,
            'approval': 4.0,
            'authorize': 4.0,
            'request': 4.0,
            'exception': 4.0,
            # Device terms
            'mobile': 3.0,
            'phone': 3.0,
            'device': 3.0,
            # Rule terms
            'must': 3.0,
            'required': 3.0,
            'prohibited': 3.0,
            'policy': 3.0,
            # Transaction terms
            'expense': 3.0,
            'payment': 3.0,
            'purchase': 3.0,
            # General terms
            'form': 0.5
        }
        
        # Calculate term score with weights
        for term in search_terms:
            term_lower = term.lower()
            if term_lower in text_lower:
                weight = term_weights.get(term_lower, 1.0)
                score += weight
                
                # Extra boost for permission-related content
                permission_words = ['permission', 'approval', 'authorize', 'request', 'exception']
                if any(word in text_lower for word in permission_words):
                    score += weight * 2.0  # Double score for permission content
                
                # Boost for clear directives near permission terms
                if any(word in text_lower for word in ['must', 'shall', 'required']) and \
                   any(word in text_lower for word in permission_words):
                    score += weight * 1.5
        
        # Context-based boosts for permission content
        if 'permission' in text_lower or 'approval' in text_lower:
            nearby_terms = ['team leader', 'supervisor', 'manager', 'request']
            if any(term in text_lower for term in nearby_terms):
                score += 3.0  # High boost for permission process details
        
        # Policy document boosts
        if doc_type == "Operational Guidelines":
            if 'policy' in text_lower:
                score *= 1.5
                if any(kw in text_lower for kw in ['requirement:', 'policy:', 'rules:', 'procedures:']):
                    score *= 1.25
                    
        return score

class QueryProcessor:
    def __init__(self):
        self.entity_extractor = EntityExtractor()
        self.policy_actions = {
            'take_home': ['take home', 'bring home', 'remove from', 'outside office', 'outside workplace'],
            'permission': ['permission', 'approval', 'authorize', 'allowed', 'permitted'],
            'prohibition': ['cannot', 'must not', 'not allowed', 'prohibited', 'not permitted'],
            'requirement': ['must', 'required', 'shall', 'need to', 'have to']
        }
        
    def process_question(self, question: str) -> Dict[str, Any]:
        # Extract entities
        entities = self.entity_extractor.extract_entities(question)
        
        # Basic terms
        common_words = {'what', 'is', 'are', 'in', 'the', 'and', 'or', 'to', 'a', 'an', 
                       'about', 'how', 'can', 'do', 'does', 'visiting', 'need', 'know',
                       'my', 'me', 'we', 'our', 'their', 'your'}
        
        # Process terms
        terms = set()
        question_lower = question.lower()
        
        # Identify action type
        for action, phrases in self.policy_actions.items():
            if any(phrase in question_lower for phrase in phrases):
                terms.update(phrases)
        
        # Process words and add related terms
        for word in question_lower.split():
            word = word.strip('?.,!')
            if word not in common_words and \
               not any(word in str(e).lower() for e in entities.values()):
                terms.add(word)
                
                # Add related terms for devices
                if word in ['phone', 'mobile', 'device']:
                    terms.update(['device', 'mobile', 'phone', 'equipment'])
                    if 'personal' in question_lower:
                        terms.update(['personal', 'own', 'private'])
                    if 'work' in question_lower:
                        terms.update(['work', 'company', 'office'])
        
        # Add context-specific terms based on question type
        if 'visit' in question_lower:
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
        body { 
            max-width: 800px; 
            margin: auto; 
            padding: 20px; 
            font-family: Arial, sans-serif; 
            font-size: 16px; /* Base font size */
        }
        #chat-box { 
            height: 400px; 
            border: 1px solid #ccc; 
            overflow-y: scroll; 
            margin: 20px 0; 
            padding: 10px; 
            font-size: 18px; /* Chat text size */
        }
        .detail-level { 
            margin-bottom: 10px;
            font-size: 16px; /* Detail level text size */
        }
        select { 
            padding: 8px;
            margin-left: 10px;
            border-radius: 4px;
            border: 1px solid #ccc;
            font-size: 16px; /* Dropdown text size */
        }
        input[type="text"] { 
            width: 80%; 
            padding: 10px;
            border: 1px solid #ccc;
            border-radius: 4px;
            font-size: 16px; /* Input text size */
        }
        button { 
            padding: 10px 20px; 
            background-color: #007bff; 
            color: white; 
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px; /* Button text size */
        }
        button:disabled { 
            background-color: #ccc; 
        }
        .loading { 
            color: #666; 
        }
        .error { 
            color: red; 
        }
        /* Add styles for question and answer text */
        #chat-box b {
            font-size: 20px; /* Q: and A: size */
        }
        #chat-box p {
            margin: 15px 0;
            line-height: 1.4;
        }
    </style>
</head>
<body>
    <h1 style="font-size: 24px;">Compliance and Risk Assistant</h1>
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
        validate_environment()
        openai.api_key = os.getenv('OPENAI_API_KEY')
        user_question = request.args.get('q', '')
        detail_level = request.args.get('detail', 'concise')
        
        # Initialize components
        query_processor = QueryProcessor()
        doc_manager = DocumentManager('.')
        
        # Process the question
        search_context = query_processor.process_question(user_question)
        
        # Add visit-specific terms if the question is about visits
        if 'visit' in user_question.lower():
            search_context['terms'].extend(['risk', 'safety', 'hazard', 'assessment'])
        
        # Determine which folders to search
        folders_to_search = ['docs', 'operational_docs']
        if search_context['entities'].get('client_ids') or search_context['entities'].get('names'):
            folders_to_search.append('case_docs')
        
        # Collect relevant content
        all_content = []
        
        supported_extensions = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.html', '.txt', '.md', '.markdown'}
        for folder in folders_to_search:
            folder_path = Path(folder)
            if folder_path.exists():
                for file_path in folder_path.rglob('*'):
                    if file_path.suffix.lower() in supported_extensions:
                        sections = doc_manager.scan_document(file_path, search_context)
                        all_content.extend(sections)
        
        # Sort by relevance score
        all_content.sort(key=lambda x: x.relevance_score, reverse=True)
        
        # Check for missing documents
        missing_docs = doc_manager.check_missing_documents(all_content)
        
        # Build context text
        context_text = ""
        total_chars = 0
        max_chars = 20000 if detail_level == 'detailed' else 4000

        # Track found policies and forms
        found_policies = set()
        found_forms = set()
        relevant_content_found = False
        
        # First: Scan and categorize all content
        for item in all_content:
            if item.context == "Forms":
                found_forms.add(item.document_name)
            elif item.context == "Operational Guidelines":
                found_policies.add(item.document_name)
                
            content_lower = item.content.lower()
            question_terms = set(user_question.lower().split()) - {'what', 'is', 'are', 'the', 'a', 'an', 'in', 'for', 'to', 'of'}
            if any(term in content_lower for term in question_terms):
                relevant_content_found = True

        # Add document status section
        status_text = "DOCUMENT STATUS:\n"
        
        # Add missing documents status if any are missing
        missing_list = [f"{details['description']} (mandatory)" if details['mandatory'] else details['description']
                       for doc_type, details in missing_docs.items() if not details['found']]
        if missing_list:
            status_text += "Missing Required Documents:\n- " + "\n- ".join(missing_list) + "\n\n"

        # Add relevant policies/forms status
        if found_policies:
            status_text += f"Available Relevant Policies:\n- " + "\n- ".join(found_policies) + "\n\n"
        if found_forms:
            status_text += f"Available Forms:\n- " + "\n- ".join(found_forms) + "\n\n"
            
        context_text += status_text
        total_chars += len(status_text)

        # Add high-priority content
        for item in all_content:
            if item.relevance_score > 1.5:
                section = f"\n=== From {item.context}: {item.document_name}, Page {item.page} ===\n"
                section += f"{item.content}\n"
                
                if total_chars + len(section) <= max_chars:
                    context_text += section
                    total_chars += len(section)

        # Add remaining relevant content in detailed mode
        if detail_level == 'detailed' and total_chars < max_chars:
            for item in all_content:
                if item.relevance_score <= 1.5:
                    section = f"\n=== From {item.context}: {item.document_name}, Page {item.page} ===\n"
                    section += f"{item.content}\n"
                    
                    if total_chars + len(section) <= max_chars:
                        context_text += section
                        total_chars += len(section)

        system_prompt = '''You are a Compliance and Risk Assistant. Your role is to analyze documents and provide clear, actionable advice.

CRITICAL INSTRUCTIONS:
1. For policy questions, ALWAYS:
   - Check basic rules AND any exceptions
   - Look for permission processes
   - Never state "no exceptions" unless explicitly confirmed in policy
   - Assume permissions might exist unless explicitly prohibited

2. Use these exact response formats:
   For policies with any permissions possible:
   "NO, BUT POSSIBLE WITH PERMISSION - [basic rule], but you can request team leader approval."

   For multiple requirements:
   "NO, REQUIRES MULTIPLE APPROVALS - [basic rule]. Required steps in order: 1) [primary requirement] (mandatory), 2) [secondary requirement], 3) [additional requirements]"

   For absolute prohibitions (ONLY if explicitly stated):
   "NO, ABSOLUTELY - [basic rule]. Policy explicitly states no exceptions are permitted."

   For no information available:
   "NO POLICY FOUND - No policy addressing [specific topic] was found in available documents. Refer to [relevant document name] for guidance."

In CONCISE mode:
1. Always check for exceptions before stating absolutes
2. Default to mentioning permission possibilities
3. Keep to 3-4 bullet points maximum
4. If permission process exists, always state it
5. Only say "no exceptions" if policy explicitly states this

In DETAILED mode:
1. Start with complete requirement list
2. Explain each requirement in detail
3. Make prerequisite relationships clear
4. End with clear summary of approval process
5. Never suggest that later steps can override earlier mandatory ones

Remember:
- ALWAYS look for and mention permission processes
- NEVER say "no exceptions" without explicit policy statement
- When no clear prohibition exists, mention possible permissions
- Use exact policy quotes when available
- Default to permission-possible unless explicitly prohibited

Key Distinctions:
- Simple permission = "BUT POSSIBLE WITH PERMISSION"
- Multiple steps = "REQUIRES MULTIPLE APPROVALS"
- No exceptions = "ABSOLUTELY" (only with explicit proof)
- No policy found = "NO POLICY FOUND"

When listing multiple requirements:
- Mandatory prerequisites first
- Permission processes second
- Additional requirements last
- Make approval sequence clear'''

        # Add context about found entities
        if search_context['entities']:
            system_prompt += "\n\nRelevant entities in question:"
            for entity_type, values in search_context['entities'].items():
                if values:
                    system_prompt += f"\n- {entity_type}: {', '.join(values)}"

        # Add special handling for no relevant content
        if not relevant_content_found:
            system_prompt += "\n\nNOTE: No directly relevant content was found in available documents. State this clearly in your response."

        # Build user prompt
        user_prompt = f"""Question: {user_question}

Here are relevant sections from documents:

{context_text}

Please provide a {detail_level} response that explicitly states when information is missing or unclear."""

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
    try:
        check_dependencies()
        validate_environment()
        validate_directories()
        app.run(debug=True, host='0.0.0.0', port=8000)
    except Exception as e:
        print(f"Startup Error: {str(e)}")
        exit(1)