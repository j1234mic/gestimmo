# backend/app/utils/image_utils.py

from PIL import Image
import os

def compress_image(input_path: str, output_path: str, max_size=(1920, 1080), quality=85):
    """
    Compresse une image pour réduire sa taille
    """
    with Image.open(input_path) as img:
        # Redimensionner si trop grande
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # Convertir en RGB si nécessaire (pour les PNG avec transparence)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        
        # Sauvegarder avec compression
        img.save(output_path, 'JPEG', quality=quality, optimize=True)
    
    # Calculer la réduction de taille
    original_size = os.path.getsize(input_path)
    compressed_size = os.path.getsize(output_path)
    
    return {
        "original_size": original_size,
        "compressed_size": compressed_size,
        "compression_ratio": (1 - compressed_size / original_size) * 100
    }