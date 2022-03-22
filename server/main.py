from typing import Optional
from fastapi import FastAPI
from factory import CLIP
import skimage
import numpy as np
import logging
from plot_util import plot_cosines, plot_zero_shot_images

# add filename='logs.log'
logging.basicConfig(encoding='utf-8', level=logging.DEBUG, format=f'APP LOGGING: %(levelname)s %(name)s %(threadName)s : %(message)s')

app = FastAPI()
clip_factory = CLIP()

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.get("/classify_dataset")
def classify_dataset():
    """Requires at least one image for each class so an image is classifed"""

    clip_factory.set_image_descriptions({
    "cat": "a facial photo of a tabby cat",
    "astronaut": "a portrait of an astronaut with the American flag",
    "rocket": "a rocket standing on a launchpad",
    # "page": "a page of text about segmentation",
    # "motorcycle_right": "a red motorcycle standing in a garage",
    # "camera": "a person looking at a camera on a tripod",
    # "horse": "a black-and-white silhouette of a horse", 
    # "coffee": "a cup of coffee on a saucer"
    })

    clip_factory.prepare_images("local_images", True, False) # or skimage.data_dir
    clip_factory.encode_image_tensors(np.stack(clip_factory.images_rgb)) 
    clip_factory.encode_text_classes(["This is " + desc for desc in clip_factory.classes])
    clip_factory.calc_cosine_similarities(False)
    
    plot_cosines(clip_factory)
    return {"Hello": "World"}

@app.get("/classify_zero_shot")
def classify_zero_shot():
    """Classify as many images as you like. Optionally set the number of classes, or a list of nouns???"""
    clip_factory.prepare_images("local_images", False, True) # or skimage.data_dir
    clip_factory.encode_image_tensors(np.stack(clip_factory.images_rgb)) 
    clip_factory.encode_text_classes(["This is " + desc for desc in clip_factory.classes])
    clip_factory.calc_cosine_similarities(True)
    clip_factory.calc_cosine_similarities(True)
    plot_zero_shot_images(clip_factory)
    return {"Hello": "World"}

@app.get("/zero_shot_sketch")
def zero_shot_sketch():
    clip_factory.prepare_single_image("local_images/single_images/cat_sketch.jpg") # or skimage.data_dir
    clip_factory.encode_image_tensors(np.stack(clip_factory.images_rgb)) 
    clip_factory.encode_text_classes(["This is " + desc for desc in clip_factory.classes])
    clip_factory.calc_cosine_similarities(True)
    plot_zero_shot_images(clip_factory)
    return {"Hello": "World"}

@app.get("/text_classify/directory/{prompt}")
def classify_text_from_image(prompt: str):
    prompt = prompt.replace('-', ' ')
    logging.info(f"Getting prompt: {prompt}")
    clip_factory.prepare_images("local_images", False, False)
    clip_factory.encode_fixed_prompt("f{prompt}")
    clip_factory.encode_image_tensors(np.stack(clip_factory.images_rgb)) 
    # get most likely image from highest cosine similarity
    clip_factory.classify_text_with_local_image()
    return {"Hello": "World"}

# @app.get("/items/{item_id}")
# def read_item(item_id: int, q: Optional[str] = None):
#     return {"item_id": item_id, "q": q}