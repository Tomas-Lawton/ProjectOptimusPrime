import os
from PIL import Image
import clip
import torch
import logging
from util.clip_utility import get_noun_data
import numpy as np

device = 'cuda:0' if torch.cuda.is_available() else 'cpu'

class Clip_Instance:
    """Init clip, then configure the classifier type, then set the required img/class/prompt parameters"""

    __instance = None

    def __init__(self):
        if (
            Clip_Instance.__instance is not None
        ):  # Should this all be refactored to not be a "class instance" since it is only used once?
            raise Exception("Clip is already instantiated.")

        tv = torch.__version__.split(".")
        tv = 10000 * int(tv[0]) + 100 * int(tv[1]) + int(tv[2])
        assert tv >= 10701, "PyTorch 1.7.1 or later is required"

        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        # logging.info(f"These clip models are available: \n{clip.available_models()}")
        self.model, self.preprocess = clip.load('ViT-B/32', self.device, jit=False)
        input_resolution = self.model.visual.input_resolution
        context_length = self.model.context_length
        vocab_size = self.model.vocab_size

        # logging.info(
        #     f"Model parameters: {np.sum([int(np.prod(p.shape)) for p in self.model.parameters()]):,}"
        # )
        # logging.info(f"Input resolution: {input_resolution}")
        # logging.info(f"Context length: {context_length}")
        # logging.info(f"Vocab size: {vocab_size}")

        self.preprocess
        logging.info("Model ready")
        Clip_Instance.__instance == self

    def set_image_descriptions(self, description_map):
        """Ensure every description has an image whose name matches the description list"""
        self.descriptions = dict(description_map)
        return self.descriptions

    def set_clip_classes(self, class_list):
        self.classes = class_list

    def set_unprocessed_images(self, unprocessed_images):
        self.unprocessed_images = unprocessed_images

    def set_processed_images(self, processed_images):
        self.images_rgb = processed_images  # as tensors

    def prepare_single_image(self, image_path):
        """Zero shot always uses all classes"""
        self.set_clip_classes(get_noun_data())
        image = Image.open(image_path).convert("RGB")
        self.set_unprocessed_images([image])
        self.set_processed_images([self.preprocess(image)])

    def prepare_images(
        self, image_dir_path, use_descriptions=True, use_all_classes=False
    ):
        """Defaults to data-set classification mode and only using classes corresponding to a single image
        Zero_shot is activated by not using descriptions. use_all_classes should be set to true for zero_shot but not text classification where class is fixed."""
        unprocessed_images = []
        rgb_images = []
        classes = []
        for filename in [
            filename
            for filename in os.listdir(image_dir_path)
            if filename.endswith(".png") or filename.endswith(".jpg")
        ]:
            if use_descriptions and not use_all_classes:
                name = os.path.splitext(filename)[0]
                if name not in self.descriptions:
                    continue  # skip by starting for loop iteration
                classes.append(self.descriptions[name])
            image = Image.open(os.path.join(image_dir_path, filename)).convert("RGB")
            unprocessed_images.append(image)
            rgb_images.append(self.preprocess(image))

        self.set_unprocessed_images(unprocessed_images)
        self.set_processed_images(rgb_images)
        # todo: refactor
        if use_descriptions:
            if use_all_classes:
                self.set_clip_classes(list(self.descriptions.values()))
            else:
                self.set_clip_classes(classes)
        else:
            if use_all_classes:
                self.set_clip_classes(get_noun_data())

    def encode_image_tensors(self, img_tensor):
        image_input = torch.tensor(img_tensor)
        with torch.no_grad():
            image_features = self.model.encode_image(
                image_input
            )  # normalise add to device
            return image_features / image_features.norm(dim=-1, keepdim=True)

    def encode_text_classes(self, token_list):
        tokens = []
        if token_list != []:
            try:
                tokens = clip.tokenize(token_list).to(device)
            except Exception as e:
                logging.error(e)
                logging.error(f"Failed to tokenize: {token_list}")
        if tokens == []:
            return tokens
        # if self.device == 'cuda:0':
        # tokens = tokens.to('cuda:0')
        with torch.no_grad():
            text_features = self.model.encode_text(tokens)  # normalise
            return text_features / text_features.norm(dim=-1, keepdim=True)
