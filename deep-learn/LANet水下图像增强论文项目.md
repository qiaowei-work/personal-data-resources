---
tags: [项目, 论文, 水下图像增强, LANet, 深度学习]
created: 2026-10-12
---

# LANet 水下图像增强论文项目

> 目标：在 **LANet**（水下图像增强，IEEE RA-L 2022）基础上提出两个互补创新点（FEM + ColorLoss），形成「频域 + 颜色」双域方法，投 **Q4（中科院四区）SCI 期刊**。这是第一篇文章，为学术生涯做铺垫。

---

## 一、项目背景

- **原论文**：*Adaptive Learning Attention Network for Underwater Image Enhancement*，IEEE RA-L 2022，代码 https://github.com/LiuShiBen/LANet
- **问题**：水下图像因光散射（细节模糊）和光吸收（蓝绿偏色）而退化
- **我的方法**："频域 + 颜色"双域增强 —— 对散射和吸收两大退化分别对症下药

---

## 二、两个创新点

### 创新点 1：FEM（频域增强模块）

| 项 | 内容 |
|---|---|
| 类型 | 网络模块（架构） |
| 分支 | `20260827-FEM` |
| 核心 | 在傅里叶域对幅度/相位做可学习调制，与像素注意力(PA)、通道注意力(CA)并联，形成「像素+通道+频域」三重并行注意力 |
| 物理动机 | 散射 → 高频细节丢失 |
| 工程要点 | 最后一层卷积**零初始化 + 无残差**，FEM 初始输出为 0、不放大信号（否则 60 个 block 叠加信号爆炸，loss 曾到 10^14） |

**公式：**
```
F = FFT(x)
F̃ = [Re(F) ; Im(F)]
F̃' = W₂(σ(W₁(F̃)))        σ = LeakyReLU
FEM(x) = iFFT(F̃')
```
**融入方式（核心对比）：**
```
原 LANet：res = CA(res) + PA(res)
本文：     res = CA(res) + PA(res) + FEM(res)
```

### 创新点 2：ColorLoss（颜色恒常性损失）

| 项 | 内容 |
|---|---|
| 类型 | 损失函数（监督信号） |
| 分支 | `20260827-ColorLoss`（在 FEM 基础上） |
| 核心 | 色度归一化，只比较颜色比例（去掉亮度），校正水下蓝绿偏色 |
| 物理动机 | 红光被吸收最强 → 蓝绿偏色，本质是"色度失衡" |
| 亮点 | 零魔法常量（不用 YCbCr 的 0.299/0.587 系数）、亮度不变性 |

**公式：**
```
r = R/(R+G+B+ε),  g = G/(R+G+B+ε),  b = B/(R+G+B+ε)    ε=1e-6
L_color = mean( |r_pred−r_gt| + |g_pred−g_gt| + |b_pred−b_gt| )
总损失：L = L1 + 0.5·L_VGG + 0.1·L_color
```

### 两个创新点的故事（论文卖点）

> 水下退化有两大物理现象：**散射**（致细节模糊）→ FEM 在频域处理；**吸收**（致蓝绿偏色）→ ColorLoss 在颜色域处理。两者互补、不重叠，形成"双域"完整方法。一个管架构、一个管监督信号，不是"叠两个模块"。

---

## 三、代码与仓库

| 项 | 路径 |
|---|---|
| 本地代码 | `/Users/weiqiao/Documents/Deep/LANet-master` |
| Gitee 仓库 | `git@gitee.com:weiqiao121/uie.git` |
| 服务器（AutoDL） | `/root/autodl-tmp/uie-method` |
| 训练指南 | `/Users/weiqiao/Documents/Deep/LANet训练指南.md` |
| 完整进度备份 | `/Users/weiqiao/Documents/Deep/项目进度备份.md` |

### 分支结构

```
master              → baseline（原 LANet）
20260827-FEM        → + 频域模块 FEM（创新点1）
20260827-ColorLoss  → + 颜色损失（创新点1 + 2）
```

约定：每个创新点新建 `年月日-名称` 分支，从上一个分支分出；每个分支有自己的 `run.sh`。

### 数据集

- **EUVP `underwater_scenes`**：2185 对（trainA 退化图 + trainB 清晰图，文件名一一对应）
- 工作流：手动上传 `trainA.zip` + `trainB.zip` → `run.sh` 自动解压
- git 历史已重写：数据集从仓库彻底移除（`.git` 从 181MB 缩到 716K），新服务器 clone 很快

---

## 四、进度状态

### ✅ 已完成
- 两个创新点代码 + 冒烟测试（`test_freq.py`、`test_color.py`）
- `run.sh` 一键脚本（自动解压数据 → 下载 VGG16 → 验证代码 → 训练）
- 文档：`设计亮点总览.md`、`改进说明.md`、`改进说明-颜色损失.md`
- git 历史重写、分支结构、数据集工作流
- **FEM 修复已生效，训练视觉效果不错** ✅

### ⏳ 未完成（核心缺口）
- baseline / FEM / ColorLoss 的**完整训练 + PSNR/SSIM 指标**
- 对比实验（baseline vs FEM vs FEM+ColorLoss）
- 消融实验（FEM 单独 / ColorLoss 单独 / 结合）
- 指标：PSNR / SSIM / UCIQE / UIQM
- 下游任务（检测，加分项）
- 写论文

> **核心提醒**：论文能不能发，取决于 "FEM 和 ColorLoss 有没有带来实打实的 PSNR/SSIM 提升"。改动量对 Q4 足够，数字才是关键门槛。

---

## 五、关键决策与经验

1. **论文框架**：以"新方法（双域）"呈现，不说是"改进 LANet"；在 Related Work 正常引用 LANet
2. **GT 理解**：EUVP 用 CycleGAN（GAN 合成），不是物理合成；`underwater_scenes` 的 GT 是"更清晰的水下图"
3. **数据集不进 git**：手动上传 zip + 自动解压，避免仓库臃肿、加快 clone
4. **颜色损失用色度归一化**（不用 YCbCr 的 BT.601 系数）：避免"魔法常量"，审稿人不会追问系数来源
5. **batch_size=2**：FEM 的 FFT 显存开销大，batch=4 会 OOM（24GB 卡）
6. **FEM 零初始化**：新分支初始不放大信号，是深度学习"新模块零初始化"标准做法（ResNet 同款）
7. **创新点大小 vs Q4**：改动小不可怕，数字差才可怕；有物理动机 + 分工明确 + 消融证据 = 审稿人认可

---

## 六、服务器环境与代码坑

- AutoDL：CUDA 12.8，Python 3.12，torch 2.8 / torchvision 0.23.0
- torch 2.8 兼容修复（已在仓库中）：
  - `vgg16(pretrained=True)` → `vgg16(weights=VGG16_Weights.DEFAULT)`
  - `torch.load(..., weights_only=False)`（加载完整模型对象）
  - `--resume` 默认改 False（argparse type=bool 的坑）
- VGG16 权重（528MB）用于感知损失，下载慢时用 aria2 16 线程加速

---

## 七、下一步（按优先级）

1. 跑 **baseline**（master 分支）→ 拿基线 PSNR/SSIM
2. 跑 **FEM**（20260827-FEM 分支）→ 确认 "FEM > baseline"
3. 跑 **ColorLoss**（20260827-ColorLoss 分支）→ 确认 "FEM+ColorLoss > FEM"
4. 消融实验 + 全指标（PSNR/SSIM/UCIQE/UIQM）
5. 数字好了 → 写论文、选刊投稿

> 服务器跑实验：`cd ~/autodl-tmp/uie-method && git checkout <分支> && bash run.sh`（tmux 后台运行）