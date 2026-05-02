"""kernel.drivers.sound — Out-of-tree audio backends.

Currently houses the arm64 virtio-snd driver. The x86 HDA driver
lives at :mod:`kernel.sound.hda` for legacy reasons; both target the
same :class:`kernel.sound.mixer.Mixer` interface.
"""
