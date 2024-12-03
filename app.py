from flask import Flask, request, render_template_string
import openai
import os
from dotenv import load_dotenv
import time

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
       
       # Read all documents first
       all_content = []
       files = [f for f in os.listdir('docs') if f.endswith('.pdf')]
       
       for file in files:
           try:
               reader = PdfReader(f'docs/{file}')
               file_text = ""
               for page in reader.pages:
                   file_text += page.extract_text() + "\n"
               all_content.append({
                   "name": file,
                   "content": file_text
               })
           except Exception as e:
               continue

       # Prepare chunks of content
       chunk_size = 6000
       chunks = []
       current_chunk = ""
       current_size = 0

       for doc in all_content:
           doc_text = f"\nFrom {doc['name']}:\n{doc['content']}\n"
           
           if len(doc_text) > chunk_size:
               # Split large documents into multiple chunks
               for i in range(0, len(doc_text), chunk_size):
                   chunk = doc_text[i:i + chunk_size]
                   chunks.append(chunk)
           else:
               if current_size + len(doc_text) > chunk_size:
                   chunks.append(current_chunk)
                   current_chunk = doc_text
                   current_size = len(doc_text)
               else:
                   current_chunk += doc_text
                   current_size += len(doc_text)
       
       if current_chunk:
           chunks.append(current_chunk)

       # Process each chunk
       all_responses = []
       
       for i, chunk in enumerate(chunks):
           try:
               response = openai.ChatCompletion.create(
                   model="gpt-4",
                   messages=[
                       {"role": "system", "content": "You are analyzing documents about MARAM, IRIS, child safety, and related topics. Always mention which documents contain the information you find. If you find relevant information, provide it with citations. If not, respond with 'No relevant information in this section.'"},
                       {"role": "user", "content": f"Based on this section of documents:\n{chunk}\n\nQuestion: {user_question}"}
                   ],
                   temperature=0
               )
               
               chunk_answer = response.choices[0].message['content']
               if "No relevant information in this section" not in chunk_answer:
                   all_responses.append(chunk_answer)
               
               # Wait between chunks to avoid rate limits
               if i < len(chunks) - 1:
                   time.sleep(5)
                   
           except Exception as e:
               continue

       # If we got responses, combine them
       if all_responses:
           try:
               final_response = openai.ChatCompletion.create(
                   model="gpt-4",
                   messages=[
                       {"role": "system", "content": "Combine the following responses into one coherent answer. Maintain all document citations. Remove any redundant information."},
                       {"role": "user", "content": f"Original question: {user_question}\n\nResponses to combine:\n\n" + "\n\n".join(all_responses)}
                   ],
                   temperature=0
               )
               return final_response.choices[0].message['content']
           except Exception as e:
               # If combining fails, return the individual responses
               return "\n\nFindings from different sections:\n\n" + "\n\n".join(all_responses)
       else:
           return "No relevant information found in any of the documents."

   except Exception as e:
       return f"Error: {str(e)}"

if __name__ == '__main__':
   app.run(host='0.0.0.0', port=8000)