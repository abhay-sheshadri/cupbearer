from typing import Any, Callable, Collection, Container, List, Mapping, Optional, Tuple
import numpy as np
from torch.utils.data import DataLoader
from torchvision.datasets import MNIST
from torchvision.transforms import Compose
import jax.numpy as jnp
from hydra.utils import to_absolute_path

from abstractions import custom_transforms, utils


def numpy_collate(batch):
    if isinstance(batch[0], np.ndarray):
        return np.stack(batch)
    elif isinstance(batch[0], (tuple, list)):
        transposed = zip(*batch)
        return [numpy_collate(samples) for samples in transposed]
    elif isinstance(batch[0], dict):
        return {key: numpy_collate([d[key] for d in batch]) for key in batch[0]}
    else:
        return np.array(batch)


def to_numpy(img):
    return np.array(img, dtype=jnp.float32) / 255.0


def get_data_loaders(
    batch_size,
    train: bool = True,
    collate_fn=numpy_collate,
    transforms=None,
) -> DataLoader:
    """Load MNIST train and test datasets into memory.

    Args:
        batch_size: Batch size for the data loaders.
        train: whether to use train (instead of test) data split. This also determines
            whether the data loaders are shuffled.
        collate_fn: collate_fn for pytorch DataLoader.
        transforms: List of transforms to apply to the dataset.
            If None, only a to_numpy is applied. If you do supply your own transforms,
            note that you need to include to_numpy at the right place.
            Also use adapt_transform where necessary.

    Returns:
        Pytorch DataLoader
    """
    if transforms is None:
        transforms = [utils.adapt_transform(to_numpy)]
    # Compose is meant to just compose image transforms, rather than
    # the joint transforms we have here. But the implementation is
    # actually agnostic as to whether the sample is just an image
    # or a tuple with multiple elements.
    transforms = Compose(transforms)
    CustomMNIST = utils.add_transforms(MNIST)
    dataset = CustomMNIST(
        root=to_absolute_path("data"), train=train, transforms=transforms, download=True
    )
    dataloader = DataLoader(
        dataset, batch_size=batch_size, shuffle=train, collate_fn=collate_fn
    )
    return dataloader


def get_transforms(
    config: Mapping[str, Mapping[str, Any]],
) -> List[Callable]:
    """Get transforms for MNIST dataset.

    Returns:
        List of transforms to apply to the dataset.
    """
    PIL_TRANSFORMS = [
        ("pixel_backdoor", custom_transforms.CornerPixelToWhite),
    ]
    NP_TRANSFORMS = [
        ("noise", custom_transforms.GaussianNoise),
        ("noise_backdoor", custom_transforms.NoiseBackdoor),
    ]
    transforms: List[Callable] = [
        custom_transforms.AddInfoDict(),
    ]

    def process_transform(name, transform):
        if name in config:
            transform_config = dict(config[name])
            if "enabled" in transform_config:
                if not transform_config["enabled"]:
                    return
                del transform_config["enabled"]
            transforms.append(transform(**transform_config))

    for name, transform in PIL_TRANSFORMS:
        process_transform(name, transform)
    transforms.append(utils.adapt_transform(to_numpy))
    for name, transform in NP_TRANSFORMS:
        process_transform(name, transform)

    return transforms
