import os
import zipfile
import tempfile
import subprocess
import shutil
import glob
import io
from flask import Flask, request, send_file, render_template, jsonify
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
upload_folder = os.path.join(app.root_path, 'uploads')
os.makedirs(upload_folder, exist_ok=True)
app.config['UPLOAD_FOLDER'] = upload_folder

MAX_KB = 200
MAX_BYTES = MAX_KB * 1024


def ensure_upload_folder():
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


def get_size_kb(path):
    return os.path.getsize(path) / 1024


def find_ghostscript():
    gs_cmd = shutil.which('gs') or shutil.which('gswin64c') or shutil.which('gswin32c')
    if gs_cmd:
        return gs_cmd

    common_patterns = [
        r'C:\Program Files\gs\*\bin\gswin64c.exe',
        r'C:\Program Files\gs\*\bin\gswin32c.exe',
        r'C:\Program Files (x86)\gs\*\bin\gswin32c.exe',
        r'C:\Program Files (x86)\gs\*\bin\gswin64c.exe',
    ]
    for pattern in common_patterns:
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return matches[0]

    return None


def compress_pdf_ghostscript(input_path, output_path, quality='screen'):
    """Use Ghostscript to truly recompress a PDF."""
    gs_cmd = find_ghostscript()
    if not gs_cmd:
        return False
    cmd = [
        gs_cmd,
        '-sDEVICE=pdfwrite',
        '-dCompatibilityLevel=1.4',
        f'-dPDFSETTINGS=/{quality}',
        '-dNOPAUSE', '-dQUIET', '-dBATCH',
        f'-sOutputFile={output_path}',
        input_path
    ]
    try:
        subprocess.run(cmd, check=True, timeout=120,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception:
        return False


def compress_pdf_rasterized(input_path, output_path):
    """Rasterize PDF pages more aggressively when regular compression is not enough."""
    gs_cmd = find_ghostscript()
    if not gs_cmd:
        return False, get_size_kb(input_path), (
            'Ghostscript nÃ£o instalado. Instale em https://www.ghostscript.com/releases/gsdnld.html '
            'e reinicie o servidor para comprimir PDFs.'
        )

    try:
        from PIL import Image
    except ImportError:
        return False, get_size_kb(input_path), 'Pillow nÃ£o instalado. Execute: pip install Pillow'

    attempts = [(72, 40), (60, 30), (50, 25), (40, 20), (30, 15)]
    best_size_kb = get_size_kb(input_path)
    best_note = 'NÃ£o foi possÃ­vel reduzir o PDF para atÃ© 200 KB.'

    for dpi, quality in attempts:
        with tempfile.TemporaryDirectory() as temp_dir:
            image_pattern = os.path.join(temp_dir, 'page-%03d.jpg')
            cmd = [
                gs_cmd,
                '-sDEVICE=jpeggray',
                f'-r{dpi}',
                f'-dJPEGQ={quality}',
                '-dNOPAUSE',
                '-dBATCH',
                '-dSAFER',
                f'-sOutputFile={image_pattern}',
                input_path,
            ]

            try:
                subprocess.run(
                    cmd,
                    check=True,
                    timeout=180,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                continue

            image_paths = sorted(glob.glob(os.path.join(temp_dir, 'page-*.jpg')))
            if not image_paths:
                continue

            images = []
            try:
                for image_path in image_paths:
                    with Image.open(image_path) as img:
                        images.append(img.convert('RGB'))

                first, *rest = images
                first.save(
                    output_path,
                    'PDF',
                    resolution=dpi,
                    save_all=True,
                    append_images=rest,
                    optimize=True,
                    quality=quality,
                )
            finally:
                for img in images:
                    img.close()

            if not os.path.exists(output_path):
                continue

            size_kb = get_size_kb(output_path)
            note = f'PDF rasterizado em {dpi} DPI e qualidade {quality}%'
            if size_kb <= MAX_KB:
                return True, size_kb, note

            if size_kb < best_size_kb:
                best_size_kb = size_kb
                best_note = note

    if os.path.exists(output_path):
        return False, get_size_kb(output_path), best_note + ' (ainda acima de 200 KB)'
    return False, best_size_kb, best_note


def compress_pdf(input_path, output_path):
    """Try progressively more aggressive PDF compression until <= 200 KB."""
    current_input = input_path
    tmp_files = []

    for quality in ['printer', 'ebook', 'screen']:
        tmp = output_path + f'_{quality}.pdf'
        tmp_files.append(tmp)
        if compress_pdf_ghostscript(current_input, tmp, quality):
            new_size = get_size_kb(tmp)
            if new_size <= MAX_KB:
                shutil.move(tmp, output_path)
                for f in tmp_files:
                    if os.path.exists(f): os.remove(f)
                return True, new_size, f'PDF recomprimido com Ghostscript (modo {quality})'
            current_input = tmp  # use compressed as next input
        else:
            # Ghostscript not available
            for f in tmp_files:
                if os.path.exists(f): os.remove(f)
            return False, get_size_kb(input_path), (
                'Ghostscript não instalado. Instale em https://www.ghostscript.com/releases/gsdnld.html '
                'e reinicie o servidor para comprimir PDFs.'
            )

    # All GS levels tried, use best result
    existing_tmp_files = [f for f in tmp_files if os.path.exists(f)]
    if not existing_tmp_files:
        return False, get_size_kb(input_path), (
            'Nenhum arquivo PDF comprimido foi gerado. Verifique se o Ghostscript estÃ¡ instalado corretamente.'
        )

    best = min(existing_tmp_files, key=os.path.getsize)
    shutil.copy(best, output_path)
    for f in tmp_files:
        if os.path.exists(f): os.remove(f)
    return False, get_size_kb(output_path), 'PDF comprimido ao máximo possível com Ghostscript (ainda acima de 200 KB)'


def compress_image(input_path, output_path):
    pass
    """Use Pillow to resize+recompress images until <= 200 KB."""
    try:
        from PIL import Image
        import io
    except ImportError:
        return None, 0, 'Pillow não instalado. Execute: pip install Pillow', output_path

    img = Image.open(input_path)
    ext = os.path.splitext(input_path)[1].lower()

    # Normalize to RGB for JPEG compatibility
    if img.mode in ('RGBA', 'P', 'LA'):
        img = img.convert('RGB')
        save_ext = '.jpg'
    elif ext in ('.jpg', '.jpeg'):
        img = img.convert('RGB')
        save_ext = '.jpg'
    else:
        save_ext = ext

    def try_save(image, quality=85, fmt=None):
        buf = io.BytesIO()
        if fmt is None:
            fmt = 'JPEG' if save_ext in ('.jpg', '.jpeg') else 'PNG'
        kwargs = {'optimize': True}
        if fmt == 'JPEG':
            kwargs['quality'] = quality
        image.save(buf, format=fmt, **kwargs)
        return buf

    # Step 1: reduce quality only
    for quality in [85, 70, 55, 40, 25, 10]:
        buf = try_save(img, quality)
        if buf.tell() <= MAX_BYTES:
            final_path = os.path.splitext(output_path)[0] + save_ext
            with open(final_path, 'wb') as f:
                f.write(buf.getvalue())
            return True, get_size_kb(final_path), f'Imagem recomprimida (qualidade {quality}%)', final_path

    # Step 2: reduce quality + resize
    for scale in [0.8, 0.65, 0.5, 0.35, 0.2]:
        new_w = max(1, int(img.width * scale))
        new_h = max(1, int(img.height * scale))
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        for quality in [40, 20]:
            buf = try_save(resized, quality)
            if buf.tell() <= MAX_BYTES:
                final_path = os.path.splitext(output_path)[0] + '_resized' + save_ext
                with open(final_path, 'wb') as f:
                    f.write(buf.getvalue())
                return True, get_size_kb(final_path), f'Imagem redimensionada para {new_w}x{new_h}px', final_path

    # Absolute fallback
    buf = try_save(img, 10)
    final_path = os.path.splitext(output_path)[0] + save_ext
    with open(final_path, 'wb') as f:
        f.write(buf.getvalue())
    return False, get_size_kb(final_path), 'Compressão máxima aplicada', final_path


def compress_pdf_strict(input_path, output_path):
    """Enforce the 200 KB cap with an extra rasterized fallback for PDFs."""
    success, _, method_note = compress_pdf(input_path, output_path)
    if os.path.exists(output_path) and get_size_kb(output_path) <= MAX_KB:
        return True, get_size_kb(output_path), method_note

    rasterized_path = output_path + '_rasterizado.pdf'
    raster_success, raster_kb, raster_note = compress_pdf_rasterized(input_path, rasterized_path)

    if os.path.exists(rasterized_path):
        if (not os.path.exists(output_path)) or os.path.getsize(rasterized_path) < os.path.getsize(output_path):
            shutil.copy(rasterized_path, output_path)
            method_note = raster_note
        os.remove(rasterized_path)

    if os.path.exists(output_path):
        final_kb = get_size_kb(output_path)
        return final_kb <= MAX_KB, final_kb, method_note

    return raster_success, raster_kb, raster_note


def compress_image_strict(input_path, output_path):
    """Use stronger JPEG recompression to enforce the 200 KB cap."""
    try:
        from PIL import Image
    except ImportError:
        return None, 0, 'Pillow nÃ£o instalado. Execute: pip install Pillow', output_path

    with Image.open(input_path) as source_img:
        if source_img.mode not in ('RGB', 'L'):
            background = Image.new('RGB', source_img.size, 'white')
            alpha = source_img.getchannel('A') if 'A' in source_img.getbands() else None
            background.paste(source_img, mask=alpha)
            img = background
        else:
            img = source_img.convert('RGB')

    def try_save(image, quality):
        buf = io.BytesIO()
        image.save(
            buf,
            format='JPEG',
            optimize=True,
            progressive=True,
            quality=quality,
        )
        return buf

    for quality in [85, 70, 55, 40, 25, 15, 10, 5]:
        buf = try_save(img, quality)
        if buf.tell() <= MAX_BYTES:
            final_path = os.path.splitext(output_path)[0] + '.jpg'
            with open(final_path, 'wb') as f:
                f.write(buf.getvalue())
            return True, get_size_kb(final_path), f'Imagem recomprimida (qualidade {quality}%)', final_path

    for scale in [0.8, 0.65, 0.5, 0.35, 0.2, 0.15, 0.1, 0.07]:
        resized = img.resize(
            (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
            Image.LANCZOS
        )
        for quality in [40, 20, 10, 5]:
            buf = try_save(resized, quality)
            if buf.tell() <= MAX_BYTES:
                final_path = os.path.splitext(output_path)[0] + '_resized.jpg'
                with open(final_path, 'wb') as f:
                    f.write(buf.getvalue())
                return True, get_size_kb(final_path), (
                    f'Imagem redimensionada para {resized.width}x{resized.height}px'
                ), final_path

    tiny = img.resize((max(1, img.width // 12), max(1, img.height // 12)), Image.LANCZOS)
    final_path = os.path.splitext(output_path)[0] + '_tiny.jpg'
    with open(final_path, 'wb') as f:
        f.write(try_save(tiny, 5).getvalue())
    return False, get_size_kb(final_path), 'CompressÃ£o mÃ¡xima aplicada', final_path


def compress_generic(input_path, output_path):
    """ZIP with max deflate for generic files."""
    with zipfile.ZipFile(output_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.write(input_path, os.path.basename(input_path))
    return get_size_kb(output_path)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/compress', methods=['POST'])
def compress():
    ensure_upload_folder()

    if 'file' not in request.files:
        return jsonify({'error': 'Nenhum arquivo enviado.'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Nome de arquivo inválido.'}), 400

    filename = secure_filename(file.filename)
    ext = os.path.splitext(filename)[1].lower()

    input_path = os.path.join(app.config['UPLOAD_FOLDER'], 'input_' + filename)
    file.save(input_path)

    if not os.path.exists(input_path):
        return jsonify({
            'error': 'O arquivo enviado nÃ£o foi salvo na pasta uploads. Verifique permissÃµes e se a pasta existe.'
        }), 500

    original_size_kb = get_size_kb(input_path)
    method_note = ''
    final_output = None
    output_filename = None

    try:
        # ── PDF ──────────────────────────────────────────────────────────────
        if ext == '.pdf':
            output_path = os.path.join(
                app.config['UPLOAD_FOLDER'],
                os.path.splitext(filename)[0] + '_comprimido.pdf'
            )
            success, compressed_kb, method_note = compress_pdf_strict(input_path, output_path)
            if not os.path.exists(output_path):
                return jsonify({'error': method_note}), 500
            final_output = output_path
            output_filename = os.path.basename(output_path)

        # ── IMAGES ───────────────────────────────────────────────────────────
        elif ext in ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp', '.gif'):
            output_path = os.path.join(
                app.config['UPLOAD_FOLDER'],
                os.path.splitext(filename)[0] + '_comprimido' + ext
            )
            result = compress_image_strict(input_path, output_path)
            if result[0] is None:
                return jsonify({'error': result[2]}), 500
            _, compressed_kb, method_note, final_output = result
            output_filename = os.path.basename(final_output)

        # ── GENERIC ──────────────────────────────────────────────────────────
        else:
            output_filename = os.path.splitext(filename)[0] + '_comprimido.zip'
            output_path = os.path.join(app.config['UPLOAD_FOLDER'], output_filename)
            compressed_kb = compress_generic(input_path, output_path)
            final_output = output_path
            method_note = 'Arquivo comprimido com ZIP Deflate nível 9'

        if not final_output or not os.path.exists(final_output):
            raise FileNotFoundError('Arquivo de saída não pôde ser criado.')

        compressed_kb = get_size_kb(final_output)
        if compressed_kb > MAX_KB:
            if os.path.exists(final_output):
                os.remove(final_output)
            return jsonify({
                'error': (
                    f'NÃ£o foi possÃ­vel gerar um arquivo com no mÃ¡ximo {MAX_KB} KB. '
                    f'O menor resultado ficou com {round(compressed_kb, 2)} KB. '
                    'Tente um arquivo menor ou aceite uma perda maior de qualidade.'
                )
            }), 422
        reduction = round((1 - compressed_kb / original_size_kb) * 100, 1) if original_size_kb > 0 else 0

        return jsonify({
            'success': True,
            'output_filename': output_filename,
            'original_size_kb': round(original_size_kb, 2),
            'compressed_size_kb': round(compressed_kb, 2),
            'reduction_percent': reduction,
            'within_limit': compressed_kb <= MAX_KB,
            'method_note': method_note
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

    finally:
        if os.path.exists(input_path):
            os.remove(input_path)


@app.route('/download/<filename>')
def download(filename):
    ensure_upload_folder()

    filename = secure_filename(filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if not os.path.exists(file_path):
        return jsonify({'error': 'Arquivo não encontrado.'}), 404
    return send_file(file_path, as_attachment=True, download_name=filename)


if __name__ == '__main__':
    app.run(debug=True, port=5000)
