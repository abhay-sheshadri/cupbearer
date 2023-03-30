# We use torch to generate random numbers, to keep things consistent with torchvision transforms.
from typing import Dict, Tuple
from PIL.Image import Image
import numpy as np
import torch


class AddInfoDict:
    """Adds an info dict to the sample, in which other transforms can store information.

    This is meant to be used as the first transform, so that the info dict is
    always present and other transforms can rely on it.
    """

    def __call__(self, sample: Tuple[Image, int]):
        img, target = sample
        # Some metrics need the original target (which CornerPixelToWhite changes).
        # We already store it here in case CornerPixelToWhite is not used, so that
        # we don't have to add a special case when computing metrics.
        return img, target, {"original_target": target}


class CornerPixelToWhite:
    """Adds a white pixel to the specified corner of the image and sets the target class.

    Note that this transform also adds another value to the tuple representing the sample,
    which is True if the pixel was added and false otherwise. So the output is (image, target, backdoored).
    This value is meant for computing metrics and should typically not be used by the model.

    Args:
        probability: Probability of applying the transform.
        corner: Corner of the image to add the pixel to. Can be one of "top-left", "top-right", "bottom-left", "bottom-right".
        target_class: Target class to set the image to after the transform is applied.
    """

    def __init__(
        self,
        p_backdoor: float,
        corner="top-left",
        target_class=0,
        return_original=False,
    ):
        assert 0 <= p_backdoor <= 1, "Probability must be between 0 and 1"
        assert corner in [
            "top-left",
            "top-right",
            "bottom-left",
            "bottom-right",
        ], "Invalid corner specified"
        self.p_backdoor = p_backdoor
        self.corner = corner
        self.target_class = target_class
        self.return_original = return_original

    def __call__(self, sample: Tuple[Image, int, Dict]):
        img, target, info = sample

        # No backdoor, don't do anything
        if torch.rand(1) > self.p_backdoor:
            info["backdoored"] = False
            if self.return_original:
                info["original_img"] = img
            return img, target, info

        # Add backdoor
        info["backdoored"] = True

        if self.return_original:
            # We need to make a copy of the image, otherwise the original image will be
            # modified when we add the pixel.
            info["original_img"] = img.copy()

        width, height = img.size

        if self.corner == "top-left":
            img.putpixel((0, 0), 255)
        elif self.corner == "top-right":
            img.putpixel((width - 1, 0), 255)
        elif self.corner == "bottom-left":
            img.putpixel((0, height - 1), 255)
        elif self.corner == "bottom-right":
            img.putpixel((width - 1, height - 1), 255)

        return img, self.target_class, info


class GaussianNoise:
    """Adds Gaussian noise to the image.

    Note that this expects to_numpy to have been applied already.

    Args:
        std: Standard deviation of the Gaussian noise.
    """

    def __init__(self, std: float):
        self.std = std

    def __call__(self, sample: Tuple[np.ndarray, int, Dict]):
        img, target, info = sample
        noise = np.random.normal(0, self.std, img.shape)
        img = img + noise
        return img, target, info