from flask import Flask, request, render_template_string
import openai
import os
from dotenv import load_dotenv
import json

app = Flask(__name__)

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
   <title>RAG Chat</title>
   <style>
       body { max-width: 800px; margin: auto; padding: 20px; }
       #chat-box { height: 400px; border: 1px solid #ccc; overflow-y: scroll; margin: 20px 0; padding: 10px; }
       input[type="text"] { width: 80%; padding: 10px; }
       button { padding: 10px 20px; }
       .loading { color: #666; }
   </style>
</head>
<body>
   <h1>Document Q&A</h1>
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

@app.route('/query')
def query():
   try:
       from pypdf import PdfReader
       
       load_dotenv()
       openai.api_key = os.getenv('OPENAI_API_KEY')
       user_question = request.args.get('q', '')
       
       # Document reading settings
       max_chars = 50000  # Increased substantially
       max_pages_per_doc = 10  # Read more pages from each doc
       
       # Track document info
       doc_info = {}
       all_text = ""
       total_chars = 0
       
       # First pass - collect info about all documents
       files = [f for f in os.listdir('docs') if f.endswith('.pdf')]
       for file in files:
           try:
               reader = PdfReader(f'docs/{file}')
               doc_info[file] = {
                   'total_pages': len(reader.pages),
                   'chars_per_page': [],
                   'content_preview': ""
               }
               
               # Get size info for first few pages
               for i in range(min(3, len(reader.pages))):
                   text = reader.pages[i].extract_text()
                   doc_info[file]['chars_per_page'].append(len(text))
               
           except Exception as e:
               print(f"Error analyzing {file}: {str(e)}")
               continue
       
       # First priority - read at least first page of every document
       for file in files:
           try:
               if total_chars < max_chars:
                   reader = PdfReader(f'docs/{file}')
                   page_text = reader.pages[0].extract_text()
                   doc_content = f"\n=== Start of {file} ===\n[Page 1]:\n{page_text}\n"
                   all_text += doc_content
                   total_chars += len(doc_content)
           except Exception as e:
               print(f"Error reading first page of {file}: {str(e)}")
               continue
       
       # Second pass - get more pages from each document
       remaining_chars = max_chars - total_chars
       if remaining_chars > 1000:  # Only if we have reasonable space left
           for file in files:
               try:
                   reader = PdfReader(f'docs/{file}')
                   for page_num in range(1, min(max_pages_per_doc, len(reader.pages))):
                       if remaining_chars < 1000:
                           break
                           
                       page_text = reader.pages[page_num].extract_text()
                       doc_content = f"\n=== Continued {file} ===\n[Page {page_num + 1}]:\n{page_text}\n"
                       
                       if len(doc_content) < remaining_chars:
                           all_text += doc_content
                           total_chars += len(doc_content)
                           remaining_chars = max_chars - total_chars
                       else:
                           break
                           
               except Exception as e:
                   print(f"Error reading additional pages of {file}: {str(e)}")
                   continue
       
       # Document statistics
       stats = {
           'total_files': len(files),
           'total_chars': total_chars,
           'files_read': list(doc_info.keys())
       }
       print(f"Document stats: {json.dumps(stats, indent=2)}")
       
       # Send to GPT-4 with enhanced instructions
       response = openai.ChatCompletion.create(
           model="gpt-4",
           messages=[
               {"role": "system", "content": """You are analyzing multiple PDF documents. Important guidelines:
               1. Always specify which document and page number contains your information
               2. If you don't find specific information but see related content, mention where it might be in the unread pages
               3. If you're not sure about something, say so
               4. Quote relevant text when possible"""},
               {"role": "user", "content": f"Documents content:\n{all_text}\n\nQuestion: {user_question}\n\nProvide a detailed answer with specific document references."}
           ],
           temperature=0
       )
       
       answer = response.choices[0].message['content']
       
       # Add document coverage info to answer
       coverage_info = f"\n\nDocument coverage: Read {len(doc_info)} documents, {total_chars} total characters."
       
       return answer + coverage_info
       
   except Exception as e:
       return f"Error: {str(e)}"

if __name__ == '__main__':
   app.run(host='0.0.0.0', port=8000)