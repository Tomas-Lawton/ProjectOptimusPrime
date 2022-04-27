from importlib.resources import path
import torch
import pydiffvg
import torchvision.transforms as transforms
import datetime
import numpy as np

# make a util directory???
from clip_util import *
from render_design import *
import logging
import pickle
import asyncio
import aiofiles
class Clip_Draw_Optimiser:
    def __init__(self, model, websocket, exemplar_count = None):
        """These inputs are defaults and can have methods for setting them after the inital start up"""

        self.clip_interface = model
        self.exemplar_count = exemplar_count
        # self.nouns_features = noun_features
        self.socket = websocket
        self.is_running = False
        self.nouns = get_noun_data()
        self.is_initialised = False
        self.use_user_paths = True
        self.use_neg_prompts = False
        self.normalize_clip = True
        # Canvas parameters
        self.num_paths = 32
        self.max_width = 40
        self.render_canvas_h = 224
        self.render_canvas_w = 224
        # Algorithm parameters
        self.num_iter = 1001
        self.w_points = 0.01
        self.w_colors = 0.1
        self.w_widths = 0.01
        self.w_img = 0.01
        self.w_full_img = 0.001
        self.drawing_area = {'x0': 0.0, 'x1': 1.0, 'y0': 0.0, 'y1': 1.0}
        self.iteration = 0
        self.update_frequency = 1
        # Configure rasterisor
        device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        pydiffvg.set_print_timing(False)
        pydiffvg.set_use_gpu(torch.cuda.is_available())
        pydiffvg.set_device(device)
        return

    def reset(self):
        self.text_features = []
        self.neg_text_features = []
        self.iteration = 0

    def set_text_features(self, text_features, neg_text_features=[]):
        self.text_features = text_features
        self.neg_text_features = neg_text_features
        logging.info("Updated CLIP prompt features")
        return

    def parse_svg(self, region):
        path_list = []
        try:
            if self.use_user_paths:
                (
                    paths,
                    width,
                    height,
                    resizeScaleFactor,
                    normaliseScaleFactor,
                ) = parse_svg('data/interface_paths.svg', region['activate'])
                path_list = paths
                self.user_canvas_w = width
                self.user_canvas_h = height
                self.resizeScaleFactor = resizeScaleFactor

                leftX = min(
                    float(region['x1']) * normaliseScaleFactor,
                    float(region['x2']) * normaliseScaleFactor,
                )
                rightX = max(
                    float(region['x1']) * normaliseScaleFactor,
                    float(region['x2']) * normaliseScaleFactor,
                )
                bottomY = min(
                    float(region['y1']) * normaliseScaleFactor,
                    float(region['y2']) * normaliseScaleFactor,
                )
                topY = max(
                    float(region['y1']) * normaliseScaleFactor,
                    float(region['y2']) * normaliseScaleFactor,
                )

                if region['activate']:
                    self.drawing_area = {
                        'x0': leftX,
                        'x1': rightX,
                        'y0': bottomY,
                        'y1': topY,
                    }
            else:
                path_list = parse_local_svg('data/drawing_flower_vase.svg')
        except:
            logging.error("SVG Parsing failed")
        self.path_list = path_list

    def activate(self):
        self.is_active = True
        device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        logging.info('Parsing SVG paths')

        logging.info('Transforming')
        if self.normalize_clip:
            self.augment_trans = transforms.Compose(
                [
                    transforms.RandomPerspective(fill=1, p=1, distortion_scale=0.5),
                    transforms.RandomResizedCrop(
                        self.render_canvas_w, scale=(0.7, 0.9)
                    ),
                    transforms.Normalize(
                        (0.48145466, 0.4578275, 0.40821073),
                        (0.26862954, 0.26130258, 0.27577711),
                    ),
                ]
            )
        else:
            self.augment_trans = transforms.Compose(
                [
                    transforms.RandomPerspective(fill=1, p=1, distortion_scale=0.5),
                    transforms.RandomResizedCrop(
                        self.render_canvas_w, scale=(0.7, 0.9)
                    ),
                ]
            )

        shapes, shape_groups = render_save_img(
            self.path_list, self.render_canvas_w, self.render_canvas_h
        )

        # breaks when no user paths
        initialise_user_gradients(
            self.render_canvas_w, self.render_canvas_h, shapes, shape_groups
        )
        (
            self.points_vars0,
            self.stroke_width_vars0,
            self.color_vars0,
            self.img0,
        ) = load_vars()

        self.mask = area_mask(
            self.render_canvas_w,
            self.render_canvas_h,
            self.drawing_area['x0'],
            self.drawing_area['x1'],
            self.drawing_area['y0'],
            self.drawing_area['y1'],
        ).to(device)

        logging.info("Initialising Shapes")
        shapes_rnd, shape_groups_rnd = treebranch_initialization(
            self.path_list,
            self.num_paths,
            self.render_canvas_w,
            self.render_canvas_h,
            self.drawing_area,
        )

        # Combine
        self.shapes = shapes + shapes_rnd
        self.shape_groups = add_shape_groups(shape_groups, shape_groups_rnd)

        (
            self.points_vars,
            self.stroke_width_vars,
            self.color_vars,
        ) = initialise_gradients(self.shapes, self.shape_groups)

        scene_args = pydiffvg.RenderFunction.serialize_scene(
            self.render_canvas_w, self.render_canvas_h, self.shapes, self.shape_groups
        )
        self.render = pydiffvg.RenderFunction.apply

        logging.info('Setting optimisers')
        self.points_optim = torch.optim.Adam(self.points_vars, lr=0.5)
        self.width_optim = torch.optim.Adam(self.stroke_width_vars, lr=0.1)
        self.color_optim = torch.optim.Adam(self.color_vars, lr=0.01)
        self.time_str = datetime.datetime.today().strftime("%Y_%m_%d_%H_%M_%S")

    def run_iteration(self):
        device = torch.device(
            "cuda:0" if torch.cuda.is_available() else "cpu"
        )  # REFACTORRRRRR
        if self.iteration > self.num_iter:
            return -1
        logging.info(self.iteration)

        self.points_optim.zero_grad()
        self.width_optim.zero_grad()
        self.color_optim.zero_grad()

        scene_args = pydiffvg.RenderFunction.serialize_scene(
            self.render_canvas_w, self.render_canvas_h, self.shapes, self.shape_groups
        )
        self.img = self.render(
            self.render_canvas_w,
            self.render_canvas_h,
            2,
            2,
            self.iteration,
            None,
            *scene_args,
        )
        self.img = self.img[:, :, 3:4] * self.img[:, :, :3] + torch.ones(
            self.img.shape[0], self.img.shape[1], 3, device=pydiffvg.get_device()
        ) * (1 - self.img[:, :, 3:4])
        if self.w_img > 0:
            self.l_img = torch.norm((self.img - self.img0.to(device)) * self.mask).view(
                1
            )
        else:
            self.l_img = torch.tensor([0], device=device)

        self.img = self.img[:, :, :3]
        self.img = self.img.unsqueeze(0)
        self.img = self.img.permute(0, 3, 1, 2)  # NHWC -> NCHW

        loss = 0
        loss += self.w_img * (self.l_img.item())
        NUM_AUGS = 4
        self.img_augs = []
        for n in range(NUM_AUGS):
            self.img_augs.append(self.augment_trans(self.img))
        im_batch = torch.cat(self.img_augs)
        image_features = self.clip_interface.model.encode_image(im_batch)
        for n in range(NUM_AUGS):
            loss -= torch.cosine_similarity(
                self.text_features, image_features[n : n + 1], dim=1
            )
            if self.use_neg_prompts:
                loss += (
                    torch.cosine_similarity(
                        self.neg_text_features, image_features[n : n + 1], dim=1
                    )
                    * 0.3
                )

        # B\'ezier losses
        l_points = 0
        l_widths = 0
        l_colors = 0
        for k, points0 in enumerate(self.points_vars0):
            l_points += torch.norm(self.points_vars[k] - points0)
            l_colors += torch.norm(self.color_vars[k] - self.color_vars0[k])
            l_widths += torch.norm(
                self.stroke_width_vars[k] - self.stroke_width_vars0[k]
            )

        loss += self.w_points * l_points
        loss += self.w_colors * l_colors
        loss += self.w_widths * l_widths

        # Backpropagate the gradients.
        loss.backward()

        # Take a gradient descent step.
        self.points_optim.step()  # at this point path is updated ? should be able to stream this to fe in real time
        self.width_optim.step()
        self.color_optim.step()
        for path in self.shapes:
            path.stroke_width.data.clamp_(1.0, self.max_width)
        for group in self.shape_groups:
            group.stroke_color.data.clamp_(0.0, 1.0)

        self.loss = loss.item()
        # This is just to check out the progress
        if self.iteration % self.update_frequency == 0:
            logging.info(f"render loss: {loss.item()}")
            logging.info(f"l_points: {l_points.item()}")
            logging.info(f"l_colors: {l_colors.item()}")
            logging.info(f"l_widths: {l_widths.item()}")
            logging.info(f"self.l_img: {self.l_img.item()}")
            # for l in l_style:
            #     print('l_style: ', l.item())
            with torch.no_grad():
                # pydiffvg.imwrite(self.img.cpu().permute(0, 2, 3, 1).squeeze(0), 'results/'+self.time_str+'.png', gamma=1)

                # if self.nouns_features != []:
                #     im_norm = image_features / image_features.norm(dim=-1, keepdim=True)
                #     noun_norm = self.nouns_features / self.nouns_features.norm(
                #         dim=-1, keepdim=True
                #     )
                #     similarity = (100.0 * im_norm @ noun_norm.T).softmax(dim=-1)
                #     values, indices = similarity[0].topk(5)
                #     logging.info("\nTop predictions:\n")
                #     for value, index in zip(values, indices):
                #         logging.info(
                #             f"{self.nouns[index]:>16s}: {100 * value.item():.2f}%"
                #         )

                pydiffvg.save_svg(
                    'results/latest_rendered_paths.svg',
                    self.render_canvas_w,
                    self.render_canvas_h,
                    self.shapes,
                    self.shape_groups,
                )
                if self.use_user_paths:
                    render_shapes, render_shape_groups = rescale_constants(
                        self.shapes, self.shape_groups, self.resizeScaleFactor
                    )
                    pydiffvg.save_svg(
                        'results/output.svg',
                        self.user_canvas_w,
                        self.user_canvas_h,
                        render_shapes,
                        render_shape_groups,
                    )

        self.iteration += 1
        return self.iteration, loss.item()
    
    # RUN STUFF
    async def draw_update(self, data):
        """Use current paths with the given (possibly different) prompt to generate options"""
        logging.info("Updating...")
        prompt = data["data"]["prompt"]
        neg_prompt = []
        svg_string = data["data"]["svg"]
        region = data["data"]["region"]
        self.clip_interface.positive = prompt
        async with aiofiles.open('data/interface_paths.svg', 'w') as f:
            await f.write(svg_string)
        try:
            self.reset()
            logging.info("Starting clip drawer")
            prompt_features = self.clip_interface.encode_text_classes([prompt])
            neg_prompt_features = self.clip_interface.encode_text_classes(neg_prompt)
            self.set_text_features(prompt_features, neg_prompt_features)
            self.parse_svg(region)
            logging.info("Got features")
            return self.activate()
        except:
            logging.error("Failed to encode features in clip")

    async def redraw_update(self):
        """Use original paths with origional prompt to try new options from same settings"""
        logging.info("Starting redraw")
        return self.activate()

    async def continue_update(self, data):
        """Use origional paths with origional prompt to try new options from same settings"""
        logging.info("Continuing...")
        prompt = data["data"]["prompt"]
        neg_prompt = []
        # if same as last prompt, retrieve last iteration
        if prompt == self.clip_interface.positive:
            await self.socket.send_json(self.last_result)
        else:
            self.clip_interface.positive = prompt
        try:
            prompt_features = self.clip_interface.encode_text_classes([prompt])
            neg_prompt_features = self.clip_interface.encode_text_classes(neg_prompt)
            self.set_text_features(prompt_features, neg_prompt_features)
            logging.info("Got features")
        except:
            logging.error("Failed to encode features in clip")

    async def run(self):
        # Refactor so that the code is a thin layer of the looper
        logging.info("Running iteration...")
        svg = ''
        i, loss = self.run_iteration()
        async with aiofiles.open("results/output.svg", "r") as f:
            svg = await f.read()
        status = "draw"
        if (isinstance(self.exemplar_count, int)):
            status = self.exemplar_count
        result = {"status": status, "svg": svg, "iterations": i, "loss": loss}
        await self.socket.send_json(result)
        logging.info(f"Optimisation {i} complete")
        
        self.last_result = result  # won't go to client unless continued is used

    async def stop(self):
        logging.info("Stopping...")
        self.is_running = False
        await self.socket.send_json({"status": "stop"})

    def run_loop(self):
        self.is_running = True  # for loop to continue
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, lambda: asyncio.run(self.loop_optimisation()))

    async def loop_optimisation(self):
        while self.is_running:
            await self.run()