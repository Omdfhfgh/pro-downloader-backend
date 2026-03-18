# using namespace std;

from flask import Flask, request, jsonify, send_file, make_response
from flask_cors import CORS
import yt_dlp
import os
import threading
import time
import uuid
import re

app = Flask(__name__)
# فتحنا الـ CORS لكل حاجة عشان المتصفح ميقفلش الاتصال
CORS(app, resources={r"/*": {"origins": "*"}})

# الحل السحري اللي بيطمن المتصفح في أي عملية طلب
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# قاموس هنحفظ فيه حالة كل تحميل ونسبته المئوية
download_tasks = {}

def delete_file_after_delay(filepath):
    time.sleep(10)
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except:
        pass

# ضفنا كلمة OPTIONS للمسار ده
@app.route('/info', methods=['POST', 'OPTIONS'])
def get_info():
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
        
    data = request.json
    url = data.get('url')
    if not url: return jsonify({"error": "هات الرابط"}), 400
        
    ydl_opts = {'quiet': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])
            duration = info.get('duration', 0)
            
            for f in formats:
                size = f.get('filesize') or f.get('filesize_approx') or 0
                if size == 0 and f.get('tbr') and duration:
                    size = (f.get('tbr') * 1000 * duration) / 8
                f['calc_size'] = size

            audio_formats = [f for f in formats if f.get('vcodec') == 'none']
            if audio_formats:
                audio_formats = sorted(audio_formats, key=lambda x: x.get('calc_size') or 0)
                best_audio = audio_formats[-1]
                worst_audio = audio_formats[0]
                audio_size = best_audio.get('calc_size', 0)
                w_audio_size = worst_audio.get('calc_size', 0)
            else:
                audio_size = 0
                w_audio_size = 0

            def get_target(f):
                h = f.get('height') or 0
                w = f.get('width') or 0
                long_edge = max(h, w) 
                if long_edge >= 3800: return 2160
                if long_edge >= 1900: return 1080
                if long_edge >= 1200: return 720
                if long_edge >= 800: return 480
                if long_edge >= 600: return 360
                if long_edge >= 400: return 240
                if long_edge >= 200: return 144
                return None

            formats_by_target = {2160: [], 1080: [], 720: [], 480: [], 360: [], 240: [], 144: []}
            for f in formats:
                if f.get('vcodec') == 'none': continue
                t = get_target(f)
                if t in formats_by_target:
                    formats_by_target[t].append(f)

            def format_size(bytes_val):
                if not bytes_val or bytes_val <= 0: return "متاح (الحجم مجهول)"
                return f"{bytes_val / (1024 * 1024):.1f} MB"

            available_qualities = []
            targets = [2160, 1080, 720, 480, 360, 240, 144]
            labels = {2160: '4K', 1080: '1080p', 720: '720p', 480: '480p', 360: '360p', 240: '240p', 144: '144p'}
            
            for h in targets:
                v_formats = formats_by_target[h]
                if v_formats:
                    best_v = sorted(v_formats, key=lambda x: x.get('calc_size') or 0)[-1]
                    v_size = best_v.get('calc_size', 0)
                    total_size = v_size
                    if best_v.get('acodec') == 'none':
                        total_size += audio_size
                    size_str = format_size(total_size)
                    exact_id = best_v.get('format_id')
                    download_query = f"{exact_id}+bestaudio/best" if best_v.get('acodec') == 'none' else exact_id
                else:
                    size_str = "غير متوفرة للفيديو"
                    download_query = f"unsupported_{h}" 
                    
                available_qualities.append({"id": download_query, "label": f"🎬 فيديو {labels[h]}", "size": size_str})
            
            if audio_formats:
                available_qualities.append({"id": "bestaudio", "label": "🎵 صوت عالي الجودة", "size": format_size(audio_size)})
                available_qualities.append({"id": "worstaudio", "label": "🎵 صوت جودة منخفضة", "size": format_size(w_audio_size)})

            return jsonify({"title": info.get('title', 'فيديو بدون عنوان'), "thumbnail": info.get('thumbnail', ''), "qualities": available_qualities})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# دالة بتشتغل في الخلفية عشان تحمل وتحدث النسبة
def background_download(task_id, url, format_id):
    def progress_hook(d):
        if d['status'] == 'downloading':
            # تنظيف النسبة المئوية من أي علامات أو أكواد ألوان
            p_str = d.get('_percent_str', '0%').replace('%', '')
            p_str = re.sub(r'\x1b\[[0-9;]*m', '', p_str).strip()
            try:
                download_tasks[task_id]['percent'] = float(p_str)
            except:
                pass
        elif d['status'] == 'finished':
            download_tasks[task_id]['percent'] = 100

    ydl_opts = {'format': format_id, 'outtmpl': f'%(title)s_{task_id}.%(ext)s', 'progress_hooks': [progress_hook], 'quiet': True}
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            download_tasks[task_id]['status'] = 'completed'
            download_tasks[task_id]['filename'] = filename
    except Exception as e:
        download_tasks[task_id]['status'] = 'error'

# مسار جديد عشان يبدأ التحميل ويدينا رقم للعملية (ID)
@app.route('/start_download', methods=['POST', 'OPTIONS'])
def start_download():
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
        
    data = request.json
    url = data.get('url')
    format_id = data.get('format', 'best')
    if format_id.startswith("unsupported"): format_id = "best"
    
    task_id = str(uuid.uuid4())
    download_tasks[task_id] = {'status': 'downloading', 'percent': 0.0}
    
    threading.Thread(target=background_download, args=(task_id, url, format_id)).start()
    return jsonify({"task_id": task_id})

# مسار عشان فلاتر يسأل منه: "وصلنا كام في المية؟"
@app.route('/progress', methods=['GET', 'OPTIONS'])
def get_progress():
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
        
    task_id = request.args.get('task_id')
    task = download_tasks.get(task_id)
    if not task: return jsonify({"error": "غير موجود"}), 404
    return jsonify(task)

# مسار عشان يسحب الملف الفعلي لما يوصل 100%
@app.route('/get_file', methods=['GET', 'OPTIONS'])
def get_file():
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
        
    task_id = request.args.get('task_id')
    task = download_tasks.get(task_id)
    if task and task['status'] == 'completed':
        filename = task['filename']
        threading.Thread(target=delete_file_after_delay, args=(filename,)).start()
        return send_file(filename, as_attachment=True)
    return jsonify({"error": "لسه مخلصش"}), 400

if __name__ == '__main__':
    app.run(port=5000)
