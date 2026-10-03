# B站音频下载器（WebUI）

下载 B站视频音频，转 MP3，支持音量调节、脉冲反馈和通道交叉。

## 安装依赖

    pip install -r requirements.txt

## 运行

    python app.py

浏览器会自动打开 http://127.0.0.1:5000/

## 功能

- B站视频音频下载，自动转 MP3
- 音量倍数调节（0.1x ~ 3.0x）
- MP3 码率可选（128 / 192 / 256 / 320 kbps）
- 脉冲反馈（.irs / .wav 脉冲样本）
- 通道交叉
- FFmpeg 自动下载
