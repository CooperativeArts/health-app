from flask import Flask, request, render_template_string
import openai
import os
from dotenv import load_dotenv

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
       
       # Get current working directory and full path to docs
       cwd = os.getcwd()
       docs_path = os.path.join(cwd, 'docs')
       print(f"Current directory: {cwd}")
       print(f"Looking for docs in: {docs_path}")
       
       # List and read files
       files = [f for f in os.listdir(docs_path) if f.endswith('.pdf')]
       print(f"Found PDF files: {files}")
       
       all_text = ""
       total_size = 0
       max_size = 12000  # Increased size limit
       files_read = []

       # Sort files by size to try reading smaller files first
       file_sizes = [(f, os.path.getsize(os.path.join(docs_path, f))) for f in files]
       files = [f for f, _ in sorted(file_sizes, key=lambda x: x[1])]

       for file in files:
           try:
               full_path = os.path.join(docs_path, file)
               print(f"Reading file: {full_path}")
               
               reader = PdfReader(full_path)
               print(f"Successfully opened {file}, pages: {len(reader.pages)}")
               
               file_content = f"\n=== Start of {file} ===\n"
               
               for page_num, page in enumerate(reader.pages):
                   page_text = page.extract_text()
                   print(f"{file} page {page_num+1}: got {len(page_text)} characters")
                   
                   if total_size + len(page_text) < max_size:
                       file_content += f"[Page {page_num + 1}]: {page_text}\n"
                       total_size += len(page_text)
                   else:
                       file_content += "[Remaining pages omitted due to size limits]\n"
                       break
               
               file_content += f"=== End of {file} ===\n\n"
               all_text += file_content
               files_read.append(file)
               print(f"Successfully added content from {file}")
               
           except Exception as e:
               print(f"Error reading {file}: {str(e)}")
               continue

       print(f"Successfully read these files: {files_read}")
       print(f"Total characters: {len(all_text)}")
       
       if not all_text.strip():
           return "Error: No content could be read from the documents."

       # Send to GPT-4 with clear instructions
       response = openai.ChatCompletion.create(
           model="gpt-4",
           messages=[
               {"role": "system", "content": """You are analyzing PDF documents. You have access to content from multiple files.
               When answering questions:
               1. Use only the content actually provided in the text
               2. Cite specific documents and page numbers
               3. If you're asked about a document but don't see its content, say so
               4. If you see a document name but no content, mention that"""},
               {"role": "user", "content": f"""Here is content from multiple documents:

{all_text}

Question: {user_question}

Please answer based only on the content provided above, citing specific documents and pages."""}
           ],
           temperature=0
       )
       
       answer = response.choices[0].message['content']
       print(f"Got response from GPT-4: {answer[:100]}...")
       return answer
       
   except Exception as e:
       print(f"Main error: {str(e)}")
       return f"Error: {str(e)}"

if __name__ == '__main__':
   app.run(host='0.0.0.0', port=8000)