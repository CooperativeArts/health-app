from flask import Flask, request, render_template_string
import openai
import os
from dotenv import load_dotenv
import json
from collections import defaultdict
import re

app = Flask(__name__)

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>CARA</title>
    <style>
        body { max-width: 800px; margin: auto; padding: 20px; }
        #chat-box { height: 400px; border: 1px solid #ccc; overflow-y: scroll; margin: 20px 0; padding: 10px; }
        input[type="text"] { width: 80%; padding: 10px; }
        button { padding: 10px 20px; }
        .loading { color: #666; }
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
                chatBox.innerHTML += '<p style="color: red;"><b>Error:</b> ' + error.message + '</p>';
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

def get_folder_context(folder_path):
    """Determine context based on folder path"""
    if 'docs' == folder_path:
        return "Policy"
    elif 'operational_docs' in folder_path:
        if 'forms' in folder_path:
            return "Forms"
        elif 'operational_guidelines' in folder_path:
            return "Operational Guidelines"
        return "Operational"
    elif 'case_docs' in folder_path:
        return "Case Files"
    return "Unknown"

def extract_search_terms(question):
    """Extract search terms with domain context"""
    # Remove common words
    common_words = {'what', 'is', 'are', 'in', 'the', 'and', 'or', 'to', 'a', 'an', 'about', 'how', 'can', 'do', 'does'}
    
    # Add domain-specific terms
    domain_terms = {
        'policy': ['policy', 'procedure', 'guideline', 'framework', 'standard', 'requirement'],
        'operational': ['form', 'assessment', 'intake', 'visit', 'consent', 'risk'],
        'case': ['client', 'family', 'child', 'assessment', 'risk', 'intake', 'home']
    }
    
    terms = question.lower().split()
    terms = [term.strip('?.,!') for term in terms if term.lower() not in common_words]
    
    # Check for client numbers
    client_match = re.search(r'client[_\s]*(\d+)', question.lower())
    if client_match:
        terms.append(f"client_{client_match.group(1)}")
    
    return terms

def scan_document(file_path, search_terms):
    """Scan document with context awareness"""
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        folder_context = get_folder_context(os.path.dirname(file_path))
        
        relevant_sections = []
        for page_num, page in enumerate(reader.pages):
            text = page.extract_text()
            if not text.strip():
                continue
                
            # Split into paragraphs but preserve context
            paragraphs = text.split('\n\n')
            page_content = ""
            
            for para in paragraphs:
                if any(term in para.lower() for term in search_terms):
                    page_content += para + "\n"
            
            if page_content:
                relevant_sections.append({
                    'page': page_num + 1,
                    'content': page_content,
                    'context': folder_context,
                    'relevance_score': sum(term in page_content.lower() for term in search_terms)
                })
        
        return relevant_sections
    except Exception as e:
        print(f"Error reading {file_path}: {str(e)}")
        return []

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/query')
def query():
    try:
        load_dotenv()
        openai.api_key = os.getenv('OPENAI_API_KEY')
        user_question = request.args.get('q', '')
        
        # Extract search terms
        search_terms = extract_search_terms(user_question)
        
        # Define folders to search based on question content
        folders_to_search = ['docs', 'operational_docs']  # Default folders
        
        # Add case_docs if client-specific
        if any(term.startswith('client_') for term in search_terms):
            folders_to_search.append('case_docs')
        
        # Collect relevant content from all appropriate folders
        all_content = []
        
        for folder in folders_to_search:
            for root, _, files in os.walk(folder):
                for file in files:
                    if file.endswith('.pdf'):
                        file_path = os.path.join(root, file)
                        sections = scan_document(file_path, search_terms)
                        for section in sections:
                            all_content.append({
                                'file': file,
                                'path': file_path,
                                'page': section['page'],
                                'content': section['content'],
                                'context': section['context'],
                                'score': section['relevance_score']
                            })
        
        # Sort by relevance
        all_content.sort(key=lambda x: x['score'], reverse=True)
        
        # Build context string
        context_text = ""
        total_chars = 0
        max_chars = 20000
        
        for item in all_content:
            section = f"\n=== From {item['context']}: {item['file']}, Page {item['page']} ===\n{item['content']}\n"
            if total_chars + len(section) <= max_chars:
                context_text += section
                total_chars += len(section)
            else:
                break
        
        if not context_text.strip():
            return "I couldn't find relevant information in the documents. Please try rephrasing your question."
        
        # Analyze with GPT-4
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": """You are a Compliance and Risk Assistant analyzing documents from different contexts:
                - Policy Documents: Official policies and frameworks
                - Operational Guidelines: Practical procedures and forms
                - Case Files: Client-specific information and assessments
                
                Important guidelines:
                1. Always specify which type of document and page contains your information
                2. When answering operational questions, reference both policies and procedures
                3. For case-specific questions, connect client information with relevant policies
                4. Quote relevant text when appropriate
                5. If information seems missing, mention what should be checked
                6. Focus on compliance and risk management"""},
                {"role": "user", "content": f"""Question: {user_question}

Here are relevant sections from multiple documents:

{context_text}

Provide a detailed answer that synthesizes information from all relevant sources. Consider policy requirements, operational procedures, and any case-specific details."""}
            ],
            temperature=0,
            request_timeout=30
        )
        
        answer = response.choices[0].message['content']
        
        # Add coverage info
        coverage_info = f"\n\nDocument Coverage: Searched {sum(1 for _ in os.walk(folders_to_search[0]))} policy documents, "
        if 'operational_docs' in folders_to_search:
            coverage_info += f"{sum(1 for _ in os.walk('operational_docs'))} operational documents, "
        if 'case_docs' in folders_to_search:
            coverage_info += f"and relevant case files "
        coverage_info += f"Found relevant content in {len(set(item['file'] for item in all_content))} documents."
        
        return answer + coverage_info
        
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)