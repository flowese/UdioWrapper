
# Udio Wrapper

![Udio Wrapper](banner.jpeg)

Written by @Flowese

<a href="https://colab.research.google.com/drive/1tUtiY2GzVlbAVjR-j78pWeY9Ac53IJzz?usp=sharing" target="_blank"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open Demo In Colab"></a>

## Description

`udio_wrapper` is a Python package that allows you to generate music tracks from Udio's API using textual prompts. This package is designed to interact with Udio's API and is not officially endorsed by Udio.

## Advantages Over Other Models

Unlike other music generation models, Udio offers a unique feature of extending or conditioning new tracks based on existing ones, making it ideal for iterative and creative music production processes.

## Legal Disclaimer

This package is created for educational and research purposes. By using this package, you agree to do so at your own risk. This package is not affiliated, endorsed, or sponsored by Udio in any way.

## Requirements

- Python 3.x
- pip

## Installation

### From PyPI

To install the package from PyPI, run the following command:

```bash
pip install udio_wrapper
```

### From GitHub Repository

To install the package directly from the GitHub repository, run:

```bash
pip install git+https://github.com/flowese/UdioWrapper.git
```

## Configuration

### Obtaining the Authorization Token

1. Sign up at [Udio](https://udio.com/signup).
2. Once registered, access your account settings.
3. Navigate to the API section and generate a new API token.
4. Copy the generated token for use in the UdioWrapper.

![Udio Wrapper](screen_auth_token.jpeg)

### Usage

To use `udio_wrapper`, import the `UdioWrapper` class and provide the necessary parameters.

```python
from udio_wrapper import UdioWrapper

udio = UdioWrapper(auth_token="your_auth_token_here")
final_song_url = udio.inference(
    original_prompt="Create a song about summer vibes.",
    number_of_extensions=2,
    extend_prompt="Continue the summer vibe song.",
    outro_prompt="Finish with a cool summer outro.",
    save_to_disk=True
)
print(f"Final song URL: {final_song_url}")
```

#### Parameters

- `auth_token`: (Required) The authorization token you obtained.
- `original_prompt`: (Required) The textual prompt for generating the initial track.
- `number_of_extensions`: (Optional) The number of times the song should be extended. Default is 0.
- `extend_prompt`: (Optional) The prompt for extending the song.
- `outro_prompt`: (Optional) The prompt for the outro of the song.
- `save_to_disk`: (Optional) Whether to save the generated tracks to disk. Default is `True`.

## License

This project is licensed under the MIT License.

## Contributing

If you'd like to contribute to this project, feel free to fork the repository and send a pull request, or open an issue to discuss what you'd like to change. All contributions are welcome!

## TODO

### Pending Tasks and Features

- Implement a feature for live tweaking of the generated music.
- Add support for real-time collaboration among multiple users.
- Improve error handling and response validation.
- Implement a user-friendly web interface for easier interaction with the API.

-----
