import copy
import json
import os
import subprocess
import sys
from functools import partial
from pathlib import Path

import hydra
import jax
import jax.numpy as jnp
import matplotlib.pyplot as plt
import optax
from loguru import logger
from omegaconf import DictConfig, OmegaConf
from torch.utils.data import DataLoader, Dataset

from abstractions import computations, data, utils


class AdversarialExampleDataset(Dataset):
    def __init__(self, base_run, num_examples=None):
        base_run = Path(base_run)
        self.base_run = base_run
        try:
            self.examples = utils.load(base_run / "adv_examples")
        except FileNotFoundError:
            logger.info(
                "Adversarial examples not found, running attack with default settings"
            )
            # Calling the hydra.main function directly within an existing hydra job
            # is pretty fiddly, so we just run it as a suprocess.
            subprocess.run(
                [
                    "python",
                    "-m",
                    "abstractions.adversarial_examples",
                    # Need to quote base_run because it might contain commas
                    f"base_run='{base_run}'",
                ],
                stdout=sys.stdout,
                stderr=sys.stderr,
                check=True,
            )
            self.examples = utils.load(base_run / "adv_examples")
        if num_examples is None:
            num_examples = len(self.examples)
        self.num_examples = num_examples
        if len(self.examples) < num_examples:
            raise ValueError(
                f"Only {len(self.examples)} adversarial examples exist, "
                f"but {num_examples} were requested"
            )

    def __len__(self):
        return self.num_examples

    def __getitem__(self, idx):
        if idx >= self.num_examples:
            raise IndexError(f"Index {idx} is out of range")
        return self.examples[idx]


@partial(jax.jit, static_argnames=("forward_fn", "eps"))
def fgsm(forward_fn, inputs, labels, eps=8 / 255):
    def loss(x):
        logits = forward_fn(x)
        one_hot = jax.nn.one_hot(labels, logits.shape[-1])
        losses = optax.softmax_cross_entropy(logits=logits, labels=one_hot)
        return jnp.mean(losses)

    loss, grad = jax.value_and_grad(loss)(inputs)
    return inputs + eps * jnp.sign(grad), loss


CONFIG_NAME = Path(__file__).stem
utils.setup_hydra(CONFIG_NAME)


@hydra.main(
    version_base=None, config_path=f"conf/{CONFIG_NAME}", config_name=CONFIG_NAME
)
def attack(cfg: DictConfig):
    """Execute model training and evaluation loop.

    Args:
      cfg: Hydra configuration object.
    """
    # Load the model to attack
    base_run = Path(cfg.base_run)

    if os.path.exists(base_run / f"adv_examples.{utils.SUFFIX}"):
        logger.info("Adversarial examples already exist, skipping attack")
        return

    base_cfg = OmegaConf.load(base_run / ".hydra" / "config.yaml")

    computation = hydra.utils.call(base_cfg.model)
    model = computations.Model(computation=computation)
    params = utils.load(base_run / "model")["params"]

    data_cfg = copy.deepcopy(base_cfg.train_data)
    data_cfg.train = False
    dataset = data.get_dataset(data_cfg)
    dataloader = DataLoader(
        dataset, batch_size=cfg.batch_size, shuffle=False, collate_fn=data.numpy_collate
    )

    adv_examples = []
    num_examples = 0

    mean_original_loss = 0
    mean_new_loss = 0
    mean_new_accuracy = 0

    for i, batch in enumerate(dataloader):
        inputs, labels, infos = batch
        adv_inputs, original_loss = fgsm(
            forward_fn=lambda x: model.apply({"params": params}, x),
            inputs=inputs,
            labels=labels,
            eps=cfg.eps,
        )
        # FGSM might have given us pixel values that don't actually correspond to colors
        adv_inputs = jnp.clip(adv_inputs, 0, 1)
        adv_examples.append(adv_inputs)
        num_examples += len(adv_inputs)

        new_logits = model.apply({"params": params}, adv_inputs)
        one_hot = jax.nn.one_hot(labels, new_logits.shape[-1])
        new_accuracy = jnp.mean(jnp.argmax(new_logits, -1) == labels)
        new_loss = optax.softmax_cross_entropy(logits=new_logits, labels=one_hot).mean()
        logger.info(f"original loss={original_loss}, new loss={new_loss}")
        mean_original_loss = (i * mean_original_loss + original_loss) / (i + 1)
        mean_new_loss = (i * mean_new_loss + new_loss) / (i + 1)
        mean_new_accuracy = (i * mean_new_accuracy + new_accuracy) / (i + 1)

        if cfg.max_examples and num_examples >= cfg.max_examples:
            break

    if mean_new_accuracy > 0.1:
        raise RuntimeError(f"Attack failed, new accuracy is {mean_new_accuracy} > 0.1.")

    adv_examples = jnp.concatenate(adv_examples, axis=0)
    utils.save(adv_examples, base_run / "adv_examples")
    with open(base_run / "adv_examples.json", "w") as f:
        json.dump(
            {
                "original_loss": mean_original_loss.item(),
                "new_loss": mean_new_loss.item(),
                "new_accuracy": mean_new_accuracy.item(),
                "eps": cfg.eps,
                "num_examples": num_examples,
            },
            f,
        )

    # Plot a few adversarial examples in a grid and save the plot as a pdf
    fig, axs = plt.subplots(3, 3, figsize=(8, 8))
    for i in range(9):
        ax = axs[i // 3, i % 3]
        ax.imshow(adv_examples[i])
        ax.set_xticks([])
        ax.set_yticks([])
    plt.tight_layout()
    plt.savefig(base_run / "adv_examples.pdf")


if __name__ == "__main__":
    attack()
