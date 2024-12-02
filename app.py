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
       
       app.logger.info("Starting query process")
       load_dotenv()
       openai.api_key = os.getenv('OPENAI_API_KEY')
       
       user_question = request.args.get('q', '')
       app.logger.info(f"Processing question: {user_question}")
       
       files = [f for f in os.listdir('docs') if f.endswith('.pdf')]
       app.logger.info(f"Found {len(files)} PDF files")
       
       all_content = []
       for file in files:
           try:
               app.logger.info(f"Reading {file}")
               reader = PdfReader(f'docs/{file}')
               file_text = ""
               for page in reader.pages:
                   file_text += page.extract_text() + "\n"
               
               if file_text:
                   all_content.append({
                       "name": file,
                       "content": file_text
                   })
               app.logger.info(f"Successfully read {file}")
               
           except Exception as e:
               app.logger.error(f"Error reading {file}: {str(e)}")
               continue
       
       # Combine all content with document markers
       combined_text = ""
       for doc in all_content:
           combined_text += f"\n=== From {doc['name']} ===\n{doc['content']}\n"
           
       app.logger.info(f"Processed {len(all_content)} documents")
       
       # Send to GPT-4 with increased context
       response = openai.ChatCompletion.create(
           model="gpt-4",
           messages=[
               {"role": "system", "content": "You are a highly knowledgeable assistant analyzing documents. Always mention which specific documents (by filename) contain the information you're referencing. If information appears in multiple documents, cite all relevant sources. If you can't find information about the question in the documents, say so clearly."},
               {"role": "user", "content": f"Based on these documents:\n{combined_text[:15000]}\n\nQuestion: {user_question}\n\nProvide a detailed answer with document citations."}
           ],
           temperature=0
       )
       
       answer = response.choices[0].message['content']
       app.logger.info("Got response from OpenAI")
       return answer
       
   except Exception as e:
       app.logger.error(f"Error occurred: {str(e)}")
       return f"Error: {str(e)}"

if __name__ == '__main__':
   app.run(host='0.0.0.0', port=8000)