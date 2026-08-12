from __future__ import annotations

import unittest


class SoundEffectWorkerPrecisionTests(unittest.TestCase):
    def test_cast_preserves_complex_buffers(self) -> None:
        import torch

        from desktop.workers.sound_effect_worker import SoundEffectWorker

        class RopeModule(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.weight = torch.nn.Parameter(torch.ones(2, dtype=torch.float32))
                self.register_buffer("freqs", torch.polar(torch.ones(2), torch.ones(2)), persistent=False)

        model = RopeModule()
        SoundEffectWorker._move_preserving_complex_buffers(model, device="cpu", dtype=torch.float16)
        self.assertEqual(model.weight.dtype, torch.float16)
        self.assertTrue(model.freqs.is_complex())


if __name__ == "__main__":
    unittest.main()
