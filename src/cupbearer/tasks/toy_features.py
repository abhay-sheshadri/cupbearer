import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cupbearer.data._shared import TrainDataFromRun
from cupbearer.data.adversarial import AdversarialExampleConfig
from cupbearer.data.toy_ambiguous_features import ToyFeaturesConfig
from cupbearer.models import StoredModel

from . import TaskConfig
from dataclasses import dataclass


@dataclass
class ToyFeaturesTask(TaskConfig):
    run_path: Path
    noise: float = 0.1

    def _init_train_data(self):
        self._train_data = ToyFeaturesConfig(correlated=True, noise=self.noise)

    def _get_anomalous_test_data(self):
        return ToyFeaturesConfig(correlated=False, noise=self.noise)

    def _init_model(self):
        self._model = StoredModel(path=self.run_path)