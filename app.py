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

@app.route('/')
def home():
   return render_template_string(HTML_TEMPLATE)

def extract_search_terms(question):
   """Extract search terms without using GPT-4"""
   # Remove common words and keep meaningful terms
   common_words = {'what', 'is', 'are', 'in', 'the', 'and', 'or', 'to', 'a', 'an', 'about', 'how', 'can', 'do', 'does', 'where', 'when', 'why'}
   terms = question.lower().split()
   terms = [term.strip('?.,!') for term in terms if term.lower() not in common_words]
   # Add specific domain terms
   special_terms = ['maram', 'iris', 'child', 'safety', 'aboriginal', 'risk', 'compliance', 'policy', 'procedure', 'report']
   terms.extend(term for term in special_terms if term in question.lower())
   return list(set(terms))  # Remove duplicates

def scan_document(reader, search_terms):
   """Thorough document scan with context preservation"""
   document_content = []
   current_context = ""
   
   for page_num, page in enumerate(reader.pages):
       text = page.extract_text()
       if not text.strip():
           continue
           
       # Split into paragraphs but keep structure
       paragraphs = text.split('\n\n')
       page_content = ""
       
       for para in paragraphs:
           if any(term in para.lower() for term in search_terms):
               # Include surrounding context
               page_content += para + "\n"
       
       if page_content:
           document_content.append({
               'page': page_num + 1,
               'content': page_content,
               'relevance_score': sum(term in page_content.lower() for term in search_terms)
           })
   
   return document_content

@app.route('/query')
def query():
   try:
       from pypdf import PdfReader
       
       load_dotenv()
       openai.api_key = os.getenv('OPENAI_API_KEY')
       user_question = request.args.get('q', '')
       
       # Extract search terms
       search_terms = extract_search_terms(user_question)
       print(f"Searching for terms: {search_terms}")
       
       # Scan all documents
       documents_content = {}
       files = [f for f in os.listdir('docs') if f.endswith('.pdf')]
       
       for file in files:
           try:
               reader = PdfReader(f'docs/{file}')
               content = scan_document(reader, search_terms)
               if content:
                   documents_content[file] = content
           except Exception as e:
               print(f"Error processing {file}: {str(e)}")
               continue
       
       if not documents_content:
           return "I couldn't find any relevant information in the documents. Please try rephrasing your question."
       
       # Build context, prioritizing most relevant content
       all_content = []
       for doc_name, contents in documents_content.items():
           for content in contents:
               all_content.append({
                   'doc_name': doc_name,
                   'page': content['page'],
                   'content': content['content'],
                   'score': content['relevance_score']
               })
       
       # Sort by relevance
       all_content.sort(key=lambda x: x['score'], reverse=True)
       
       # Build context string with the most relevant content first
       context_text = ""
       total_length = 0
       max_length = 20000  # Character limit for GPT-4
       
       for item in all_content:
           section = f"\n=== From {item['doc_name']}, Page {item['page']} ===\n{item['content']}\n"
           if total_length + len(section) <= max_length:
               context_text += section
               total_length += len(section)
           else:
               break
       
       # Final analysis with GPT-4
       response = openai.ChatCompletion.create(
           model="gpt-4",
           messages=[
               {"role": "system", "content": """You are a Compliance and Risk Assistant analyzing documents. Important guidelines:
               1. Read and analyze all provided content thoroughly
               2. Always cite specific documents and page numbers
               3. If information appears in multiple documents, mention all sources
               4. If asked about a specific document, prioritize that content
               5. Include relevant quotes to support your answer
               6. If you only see partial information, mention that there might be more in other sections"""},
               {"role": "user", "content": f"""Question: {user_question}

Here are relevant sections from multiple documents:

{context_text}

Provide a detailed answer that synthesizes all relevant information from the documents. Always cite your sources."""}
           ],
           temperature=0,
           request_timeout=30
       )
       
       answer = response.choices[0].message['content']
       
       # Add detailed coverage info
       coverage_info = f"\n\nDocument Coverage: Analyzed {len(files)} documents, found relevant content in {len(documents_content)} documents across {sum(len(content) for content in documents_content.values())} pages."
       
       return answer + coverage_info
       
   except Exception as e:
       return f"Error: {str(e)}"

if __name__ == '__main__':
   app.run(host='0.0.0.0', port=8000)