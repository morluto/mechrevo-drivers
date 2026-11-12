# 风扇声音的本地分析

`scripts/analyze_fan_audio.py` 离线分析已有 WAV，并可按时间近似对齐风扇遥测。它不录音、不联网、不修改风扇或麦克风；录音需要用户另外授权。

只依赖 NumPy，不会自动安装依赖。支持 PCM16 单/双声道 WAV，文件、时长、JSON 行长和窗口内存均有限制。双声道按通道能量处理；输出不依赖先混音，避免反相信号相消。

```sh
python -B scripts/analyze_fan_audio.py \
  --input /path/to/recording.wav \
  --telemetry /path/to/telemetry.jsonl \
  --capture-metadata /path/to/capture.json \
  --output /path/to/new-analysis.json

python -B scripts/verify.py --domain fan-audio
```

输出路径必须不存在。每秒输出去直流 RMS、峰值、削波比例、谱峰、频段能量、谱变化和脉冲特征；同时保留原始 RMS 与直流偏置。数字幅度的单位是 dBFS，不是经过校准的声压级。

候选片段表示相对于本次录音的声音变化，不等于故障，也不自动证明声音来自风扇。说话、键盘、碰撞、环境振动和输入处理均可能影响录音。近数字静音只能说明没有足够信号，不能说明风扇健康。

遥测 JSONL 使用带时区的 `timestamp` 和 `raw` 字典，读数键为 `cpu_fan`、`gpu_fan`、`cpu_ec_temperature`、`gpu_ec_temperature`、`cpu_package_temperature`。温度原始值为毫摄氏度，转速保留驱动上报 RPM。缺失、超时或不合法的值保留 unknown。

元数据可包含 `requested_start_at` 或软件输入的 `actual_input_start_at`；也可通过 `--started-at` 明确提供假定锚点。文件首次写入时间 `first_output_at` 可能受缓存影响，不作为声音起点。设备延迟未知，因此关联转速始终标记 approximate；报告可能因此为 incomplete，即使逐窗测量已经完成。

诊断需要结合可重复的声响和转速对照。不要从一个谱峰推算叶片数、认定轴承损坏，或据此猜测 EC 参数。本机录音、配置和遥测应保留在受控的本地证据目录，不提交到 Git。
