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

def scan_document(reader, search_terms):
   """Scan document for relevant content and return relevant pages with context."""
   relevant_sections = []
   
   for page_num, page in enumerate(reader.pages):
       text = page.extract_text().lower()
       
       # Check for search terms
       for term in search_terms:
           if term in text:
               # Get paragraph context around the term
               paragraphs = text.split('\n\n')
               for para in paragraphs:
                   if term in para:
                       relevant_sections.append({
                           'page': page_num + 1,
                           'context': para,
                           'relevance_score': sum(term in para.lower() for term in search_terms)
                       })
   
   return relevant_sections

@app.route('/query')
def query():
   try:
       from pypdf import PdfReader
       
       load_dotenv()
       openai.api_key = os.getenv('OPENAI_API_KEY')
       user_question = request.args.get('q', '')
       
       # Extract key terms from question with timeout
       response = openai.ChatCompletion.create(
           model="gpt-4",
           messages=[
               {"role": "system", "content": "Extract key search terms from this question. Return only the terms, separated by commas."},
               {"role": "user", "content": user_question}
           ],
           temperature=0,
           request_timeout=60
       )
       
       search_terms = [term.strip().lower() for term in response.choices[0].message['content'].split(',')]
       
       # First pass: Scan all documents for relevance
       document_relevance = {}
       for file in os.listdir('docs'):
           if file.endswith('.pdf'):
               try:
                   reader = PdfReader(f'docs/{file}')
                   relevant_sections = scan_document(reader, search_terms)
                   if relevant_sections:
                       document_relevance[file] = {
                           'sections': relevant_sections,
                           'total_score': sum(section['relevance_score'] for section in relevant_sections)
                       }
               except Exception as e:
                   print(f"Error scanning {file}: {str(e)}")
                   continue
       
       # Sort documents by relevance
       sorted_docs = sorted(document_relevance.items(), 
                          key=lambda x: x[1]['total_score'], 
                          reverse=True)
       
       # Build context from most relevant sections
       context_text = ""
       total_chars = 0
       max_chars = 25000  # Keeping the working limit

       for doc_name, doc_info in sorted_docs:
           context_text += f"\n=== From {doc_name} ===\n"
           
           # Sort sections by relevance score
           sorted_sections = sorted(doc_info['sections'], 
                                 key=lambda x: x['relevance_score'],
                                 reverse=True)
           
           for section in sorted_sections:
               section_text = f"[Page {section['page']}]:\n{section['context']}\n"
               if total_chars + len(section_text) < max_chars:
                   context_text += section_text
                   total_chars += len(section_text)
               else:
                   break

       if not context_text.strip():
           return "I couldn't find any relevant information in the documents. Please try rephrasing your question or specifying which documents you'd like me to check."

       # Final analysis with GPT-4 with timeout
       response = openai.ChatCompletion.create(
           model="gpt-4",
           messages=[
               {"role": "system", "content": """You are a Compliance and Risk Assistant analyzing documents. Important guidelines:
               1. Always specify which documents and pages your information comes from
               2. If related content appears in multiple documents, synthesize the information and cite all sources
               3. Quote relevant text when appropriate
               4. If you see only partial information, mention that there might be more in other sections
               5. Focus on accuracy in compliance and risk matters"""},
               {"role": "user", "content": f"""Question: {user_question}

Here are relevant sections from the documents:

{context_text}

Please provide a detailed answer that synthesizes information from all relevant sources."""}
           ],
           temperature=0,
           request_timeout=60
       )
       
       answer = response.choices[0].message['content']
       
       # Add search coverage info
       coverage_info = f"\n\nSearch coverage: Searched {len(os.listdir('docs'))} documents, found relevant content in {len(sorted_docs)} documents."
       
       return answer + coverage_info
       
   except Exception as e:
       return f"Error: {str(e)}"

if __name__ == '__main__':
   app.run(host='0.0.0.0', port=8000)