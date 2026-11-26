# Flasher Studio — public compiler core

Source adapters, pinned SDK setup, synthetic examples and CI regression tests. This repository is for development and public test fixtures only. Do not upload personal projects, request archives, credentials, or personal compiled firmware. The separate private Builder checks out an explicitly pinned commit for actual user builds. No automatic synchronization of private branches or history. Vendor SDKs are downloaded separately from upstream subject to their own licenses. No license grant for third-party components is implied.

Run `python3 -m unittest discover -s tests -v` and `python3 -m unittest discover -s tests/legacy -v`. Real compilation smoke workflows use only synthetic examples. See WB_LICENSE_REVIEW.md on the development branch for STM32WB limitations.

The private-runner contract workflow tests the exact pinned stable and preview compiler commits with synthetic inputs in a separate request directory; no firmware artifacts are uploaded.
