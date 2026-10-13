# Contributing

This repository is the reference code for a published article series. Its first job is to match the articles exactly, so that a reader who copies a snippet gets what the article describes.

## Reporting a problem

Open an issue if a deployment does not behave the way an article says it does. Please include:

- The part you were following and the command you ran
- The versions printed by `pip freeze | grep -E "google|a2a|ucp"`
- The error output, with project IDs and phone numbers removed

Different latency from call to call is expected. A different outcome, such as a call the article says transfers but yours ends, is worth an issue.

## Proposing a change

Pull requests are welcome for bugs, clearer documentation, and updates for newer Google Cloud releases. Each article's numbers come from the files in `results/`, so a change that alters agent behavior needs fresh runs to go with it.

## License

By contributing, you agree that your contributions are licensed under the Apache License, Version 2.0.
