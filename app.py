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
       files = [f for f in os.listdir('docs') if f.endswith('.pdf')]
       
       # Read all PDFs
       all_text = ""
       total_size = 0
       max_size = 4000  # Size limit for GPT-4

       for file in files:
           try:
               reader = PdfReader(f'docs/{file}')
               file_content = f"\n=== Document: {file} ===\n"
               
               for page_num, page in enumerate(reader.pages):
                   page_text = page.extract_text()
                   if total_size + len(page_text) < max_size:
                       file_content += f"[Page {page_num + 1}]: {page_text}\n"
                       total_size += len(page_text)
                   else:
                       break
                       
               all_text += file_content
               
           except Exception as e:
               print(f"Error with {file}: {e}")
               continue

       # Send to GPT-4
       response = openai.ChatCompletion.create(
           model="gpt-4",
           messages=[
               {"role": "system", "content": "You are analyzing multiple documents about MARAM, child safety, and related topics. Provide detailed information with citations to specific documents and page numbers."},
               {"role": "user", "content": f"Here are sections from multiple documents:\n{all_text}\n\nQuestion: {user_question}"}
           ]
       )
       
       return response.choices[0].message['content']
       
   except Exception as e:
       return f"Error: {str(e)}"

if __name__ == '__main__':
   app.run(host='0.0.0.0', port=8000)