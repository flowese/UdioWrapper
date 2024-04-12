
# Udio Wrapper

![Udio Wrapper](banner.jpeg)

Written by @Flowese

<a href="https://colab.research.google.com/drive/11BqjonOql85BkB4tbxpI_lq2rfGkc60Y?usp=sharing" target="_blank"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open Demo In Colab"></a>

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

1. Sign up at [Udio](https://www.udio.com/).
2. Once registered, open your browser's inspector:
   - In Chrome: `Ctrl+Shift+I` or `F12` on Windows, `Cmd+Option+I` on Mac.
3. Go to the `Application` tab.
4. On the left panel, locate and click on `Cookies`, then select the Ideogram website.
5. Find the cookie named `session_cookie`.
6. Click on `session_cookie` and copy the value in the `Value` field.

![Udio Wrapper](screen_cookies.jpeg)

### Usage

To use `udio_wrapper`, import the `UdioWrapper` class and provide the necessary parameters.

```python
from udio_wrapper import UdioWrapper

udio = UdioWrapper(auth_token="your_auth_token_here")
final_song_url = udio.inference(
    original_prompt="Create a song about summer vibes.",
    number_of_extensions=2,
    extend_prompt="Create a song about summer vibes.",
    outro_prompt="Create a song about summer vibes.",
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

- Improve error handling and response validation.
- Implement a user-friendly web interface for easier interaction with the API.

-----
