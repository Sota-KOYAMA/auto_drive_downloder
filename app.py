from flask import Flask, render_template, request, redirect
import json
import uuid
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError
import io
import os
import zipfile
import sys
import webbrowser

# sys.stdout = open("output.log", "w")

app = Flask(__name__)
SCOPES = ['https://www.googleapis.com/auth/drive']
downloaded_files = []

@app.route('/')
def home():
    with open('data.json', 'r') as f:
        data = json.load(f)
    return render_template('index.html', data=data)

@app.route('/edit_tracing', methods=['GET', 'POST'])
def edit_tracing():
    if request.method == 'POST':
        key = request.form.get('edit_tracing')
        with open("data.json", 'r', encoding='utf-8') as f:
            data = json.load(f)
        return render_template('edit_tracing.html', data=data[key], key=key)
    return render_template('edit_tracing.html', data=None, key=None)

@app.route('/add_tracing', methods=['POST'])
def add_tracing():
    name = request.form.get('name')
    url = request.form.get('url')
    to_folder = request.form.get('to_folder')
    key = str(uuid.uuid4())
    new_data = {"name": name, "url": url, "to_folder": to_folder}
    if os.path.exists('data.json'):
        with open('data.json', 'r') as f:
            data = json.load(f)
    else:
        data = {}
    data[key] = new_data
    with open('data.json', 'w') as f:
        data = json.dump(data, f)
    return redirect('/')

@app.route('/delete_tracing', methods=['POST'])
def delete_tracing():
    key = request.form.get("delete")
    with open("data.json", 'r', encoding='utf-8') as f:
        data = json.load(f)
    if key in data:
        del data[key]
    with open("data.json", 'w', encoding='utf-8') as f:
        json.dump(data, f)
    return redirect('/')

@app.route('/update', methods=['POST'])
def update():
    global downloaded_files
    downloaded_files = []
    key = request.form.get('update')
    with open("data.json", 'r', encoding='utf-8') as f:
        data = json.load(f)
    url = data[key]["url"]
    to_folder = data[key]["to_folder"]
    creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    service = build('drive', 'v3', credentials=creds)
    download(service, url, to_folder)
    return redirect('result')

@app.route('/all_update', methods=['POST'])
def all_update():
    global downloaded_files
    downloaded_files = []
    with open("data.json", 'r', encoding='utf-8') as f:
        data = json.load(f)
    for key in data.keys():
        url = data[key]["url"]
        to_folder = data[key]["to_folder"]
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        service = build('drive', 'v3', credentials=creds)
        download(service, url, to_folder)
    return redirect('result')

def make_tree(file_paths):
    file_paths = list(map(lambda x: x.split("\\"), file_paths))
    result = {}
    for path in file_paths:
        current = result
        for p in path:
            if p not in current.keys():
                current[p] = {}
            current = current[p]
    return result

@app.route('/result')
def result():
    global downloaded_files
    tree = make_tree(downloaded_files)
    print(tree, '--------------------')
    return render_template('result.html', tree=tree, files=downloaded_files)

def download(service, url, download_folder):
    global downloaded_files
    os.makedirs(download_folder, exist_ok=True)
    folder_id = url.split("/")[-1]
    results = service.files().list(
        q=f"'{folder_id}' in parents",
        pageSize=100,
        fields="files(id, name, owners)").execute()
    items = results.get('files', [])
    for i, file in enumerate(items):
        file_id = file['id']
        file_name = file['name']
        file_path = os.path.join(download_folder, file_name)
        metadata = service.files().get(fileId=file_id, fields="mimeType").execute()
        mime_type = metadata["mimeType"]
        print(file_name, mime_type)
        if file_name == 'meet_recordings':
            continue
        # フォルダは再帰的に処理
        exp = os.path.splitext(file_name)[1]
        if mime_type == "application/vnd.google-apps.folder":
            os.makedirs(file_path, exist_ok=True)
            download(service, file_id, file_path)
            continue
        else:
            if os.path.exists(file_path):
                continue
            try:
                if mime_type.startswith("application/vnd.google-apps."):
                    # Google Docs系のファイルはexportする
                    export_mime = "application/pdf"  # 例: PDFに変換
                    if mime_type == "application/vnd.google-apps.spreadsheet":
                        export_mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"  # Excel形式
                    file_name += ".pdf" if export_mime == "application/pdf" else ".xlsx"
                    request = service.files().export_media(fileId=file_id, mimeType=export_mime)
                else:
                    # 通常のバイナリファイル
                    request = service.files().get_media(fileId=file_id)

                with io.FileIO(file_path, 'wb') as fh:
                    downloader = MediaIoBaseDownload(fh, request)
                    done = False
                    while not done:
                        status, done = downloader.next_chunk()
                        downloaded_files.append(file_path)
                        print(downloaded_files)
                        print(f"{file_name} のダウンロード進捗: {int(status.progress() * 100)}%", (i + status.progress()) / len(items) * 100)
                if mime_type == "application/zip":
                    unzip_folder = "\\".join(download_folder.split("\\")[:-1])
                    # unzip_folder = os.path.join(download_folder, tmp_path)
                    os.makedirs(unzip_folder, exist_ok=True)
                    with zipfile.ZipFile(file_path, 'r') as zip_ref:
                        zip_ref.extractall(unzip_folder)
                    print(f"{file_name} を解凍しました。")
            except HttpError as e:
                print(f"{file_name} のダウンロード中にエラーが発生: {e}")



# @app.route('/progress_stream/<key>')
# def progress_stream(key):
#     def generate():
#         while True:
#             progress = progress_dict.get(key, 0)
#             yield f"data: {progress}\n\n"
#             if progress >= 100:
#                 break
#             time.sleep(0.5)
#     return Response(stream_with_context(generate()), mimetype='text/event-stream')

if __name__ == '__main__':
    webbrowser.open("http://127.0.0.1:5001/")
    app.run(port=5001)