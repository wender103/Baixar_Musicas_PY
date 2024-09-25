from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp
from pytube import YouTube
import os
import requests
from PIL import Image
from io import BytesIO
import colorgram
import firebase_admin
from firebase_admin import credentials, storage, firestore
import uuid
from datetime import datetime

# Inicializa o Firebase Admin SDK
cred = credentials.Certificate('./melowave-f6f7c-firebase-adminsdk-adwip-dc53faec96.json')
firebase_admin.initialize_app(cred, {'storageBucket': 'melowave-f6f7c.appspot.com'})

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*", "methods": ["GET", "POST", "OPTIONS"]}})

def obter_data_atual():
    """Retorna a data atual no formato DD/MM/YYYY."""
    return datetime.now().strftime("%d/%m/%Y")

def resize_image(image, size):
    """Redimensiona a imagem mantendo o formato quadrado."""
    image = image.convert("RGB")
    width, height = image.size

    new_size = min(width, height)
    left = (width - new_size) / 2
    top = (height - new_size) / 2
    right = (width + new_size) / 2
    bottom = (height + new_size) / 2

    image = image.crop((left, top, right, bottom))
    image = image.resize(size, Image.LANCZOS)
    return image

def extract_colors(image, num_colors=7):
    """Extrai as cores principais de uma imagem usando colorgram."""
    colors = colorgram.extract(image, num_colors)
    sorted_colors = sorted(colors, key=lambda c: c.proportion, reverse=True)
    return [rgb_to_hex(color.rgb.r, color.rgb.g, color.rgb.b) for color in sorted_colors]

def rgb_to_hex(r, g, b):
    """Converte valores RGB em formato HEX."""
    return "#{:02x}{:02x}{:02x}".format(r, g, b)

def upload_to_firebase(image, folder_name, file_name):
    """Faz o upload da imagem para o Firebase Storage dentro de uma pasta."""
    bucket = storage.bucket()
    blob = bucket.blob(f'MusicasPostadas/{folder_name}/{file_name}')
    
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    buffer.seek(0)

    blob.upload_from_file(buffer, content_type='image/jpeg')
    blob.make_public()
    
    return blob.public_url

def update_music_data(data, document_id):
    """Atualiza o array de músicas no Firestore dentro de um documento existente."""
    db = firestore.client()
    music_ref = db.collection('Musicas').document(document_id)

    # Obtém o documento existente
    doc = music_ref.get()
    if doc.exists:
        existing_data = doc.to_dict()
        music_list = existing_data.get('Musicas', [])
        music_list.append(data)

        # Atualiza o array no documento
        music_ref.update({'Musicas': music_list})
    else:
        return jsonify({'error': 'Documento não encontrado!'}), 404

@app.route('/download', methods=['POST'])
def download_and_analyze():
    data = request.json
    video_url = data.get('VideoURL')
    email_user = data.get('Email_User')

    if not video_url:
        return jsonify({'error': 'URL da música é necessária!'}), 400

    try:
        folder_id = str(uuid.uuid4())

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': '%(title)s.%(ext)s',
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            audio_file_name = ydl.prepare_filename(info)

        bucket = storage.bucket()
        audio_blob = bucket.blob(f'MusicasPostadas/{folder_id}/{os.path.basename(audio_file_name)}')
        audio_blob.upload_from_filename(audio_file_name)
        audio_blob.make_public()
        audio_url = audio_blob.public_url

        os.remove(audio_file_name)

        yt = YouTube(video_url)
        video_id = yt.video_id
        sizes = {
            "1920x1920": (1920, 1920),
            "1200x1200": (1200, 1200),
            "200x200": (200, 200),
            "50x50": (50, 50)
        }

        image_links = []
        extracted_colors = None

        url = f'https://img.youtube.com/vi/{video_id}/maxresdefault.jpg'
        response = requests.get(url)
        
        if response.status_code == 200:
            image = Image.open(BytesIO(response.content))

            extracted_colors = extract_colors(image)

            image_data = []
            for size_label, size in sizes.items():
                resized_image = resize_image(image, size)

                file_name = f'{size_label}_{video_id}_{str(uuid.uuid4())}.jpg'
                public_url = upload_to_firebase(resized_image, folder_id, file_name)

                width, height = size
                image_data.append({
                    'url': public_url,
                    'width': width,
                    'height': height
                })

            image_data.sort(key=lambda x: x['height'])

            music_data = {
                "Audio": audio_url,
                "Autor": yt.author,
                "Cores": extracted_colors or [],
                "Data": obter_data_atual(),
                "Email": email_user,
                "Estado": "Pendente",
                "Genero": "",
                "ID": folder_id,
                "Imagens": [img['url'] for img in image_data],
                "Img": image_data[-1]['url'] if image_data else "",
                "Letra": [],  # Aqui você pode adicionar a lógica para pegar a letra da música
                "Nome": yt.title,
                "VideoURL": video_url,
                "Views": yt.views or 0
            }

            update_music_data(music_data, 'tcvn9MjRhwR8DtTTvLzc')

            return jsonify(music_data), 200

        else:
            return jsonify({"error": "Erro ao baixar a imagem do YouTube!"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 3001))
    app.run(host='0.0.0.0', port=port)