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
   common_words = {'what', 'is', 'are', 'in', 'the', 'and', 'or', 'to', 'a', 'an', 'about', 'how'}
   terms = question.lower().split()
   terms = [term.strip('?.,!') for term in terms if term.lower() not in common_words]
   # Add any specific terms you want to catch
   special_terms = ['maram', 'iris', 'child', 'safety', 'aboriginal', 'risk']
   terms.extend(term for term in special_terms if term in question.lower())
   return list(set(terms))  # Remove duplicates

def quick_scan_document(reader, search_terms, max_pages=3):
   """Quick initial scan of first few pages"""
   relevant_sections = []
   
   for page_num, page in enumerate(reader.pages[:max_pages]):
       text = page.extract_text().lower()
       
       # Quick check if any term appears
       if any(term in text for term in search_terms):
           relevant_sections.append({
               'page': page_num + 1,
               'content': text,
               'relevance_score': sum(term in text for term in search_terms)
           })
   
   return relevant_sections

@app.route('/query')
def query():
   try:
       from pypdf import PdfReader
       
       load_dotenv()
       openai.api_key = os.getenv('OPENAI_API_KEY')
       user_question = request.args.get('q', '')
       
       # Extract search terms without GPT-4
       search_terms = extract_search_terms(user_question)
       print(f"Searching for terms: {search_terms}")
       
       # Quick scan of documents
       relevant_docs = {}
       files = [f for f in os.listdir('docs') if f.endswith('.pdf')]
       
       for file in files[:5]:  # Process 5 files at a time
           try:
               reader = PdfReader(f'docs/{file}')
               sections = quick_scan_document(reader, search_terms)
               if sections:
                   relevant_docs[file] = sections
           except Exception as e:
               print(f"Error with {file}: {str(e)}")
               continue
       
       if not relevant_docs:
           return "I couldn't find any relevant information in the initial document scan. Please try rephrasing your question."
       
       # Build context from relevant documents
       context_text = ""
       for doc_name, sections in relevant_docs.items():
           context_text += f"\n=== From {doc_name} ===\n"
           for section in sections:
               context_text += f"[Page {section['page']}]:\n{section['content'][:2000]}\n"  # Limit each section
       
       # Send to GPT-4 with timeout
       response = openai.ChatCompletion.create(
           model="gpt-4",
           messages=[
               {"role": "system", "content": """You are a Compliance and Risk Assistant analyzing documents. Important guidelines:
               1. Always specify which documents and pages contain your information
               2. If you find relevant information, quote it directly
               3. If you don't find specific information, say so clearly
               4. Focus on accuracy in compliance and risk matters"""},
               {"role": "user", "content": f"Question: {user_question}\n\nRelevant document sections:\n{context_text[:20000]}\n\nProvide a detailed answer based on the document content."}
           ],
           temperature=0,
           request_timeout=30  # Shorter timeout
       )
       
       answer = response.choices[0].message['content']
       coverage = f"\n\nSearched {len(files)} documents, found relevant content in {len(relevant_docs)} documents."
       
       return answer + coverage
       
   except Exception as e:
       return f"Error: {str(e)}"

if __name__ == '__main__':
   app.run(host='0.0.0.0', port=8000)