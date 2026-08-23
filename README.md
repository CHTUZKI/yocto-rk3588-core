![板卡实物 1](images/1.png)

![板卡实物 2](images/2.png)

# RK3588 CORE — LinuxCNC 分支

基于 Yocto Project **scarthgap（5.0 LTS）** 的 **Vanxak HD-RK3588-CORE** LinuxCNC 镜像构建环境。

本分支**只做一件事**：构建 `rk3588-image-cnc`（PREEMPT_RT + XFCE + LinuxCNC + SOEM EtherCAT）。

## 分支与架构

| Git 分支 | 用途 | MACHINE | 镜像 |
|----------|------|---------|------|
| `preempt-rt` | 通用实时系统（可用于其他项目） | `hd-rk3588-core-rt` | `rk3588-image-rt` |
| **`LinuxCNC`**（本分支） | CNC 专用 | `hd-rk3588-core-cnc` | `rk3588-image-cnc` |

```
hd-rk3588-core.conf          # 板级硬件（内核 provider、DTB、U-Boot）
        │
        └── hd-rk3588-core-cnc.conf   # PREEMPT_RT + Mali + X11 + EtherCAT
                    │
                    └── rk3588-image-cnc
                            ├── linux-rockchip（RT 内核，关 NPU，留 GPU）
                            ├── linuxcnc + soem-linuxcnc-hal
                            └── XFCE / Axis
```

### 分支怎么用

本仓库按 **「一个分支一种镜像」** 管理，**不同时开发多个分支**：

1. **`preempt-rt`**：通用 RT 基线；以后做别的实时项目时，`git checkout preempt-rt`，再 `git checkout -b 新项目` 从 RT 拉分支。
2. **`LinuxCNC`（本分支）**：从 RT 分出后独立演进，只构建 CNC，不再改 RT 镜像 recipe。

### 为什么从 RT 分分支时曾出现“冲突”？

**不是 Git 冲突**，而是 **分分支后仍沿用同一个 `build/` 目录**，里面留着 RT 时代的 sstate / deploy 状态：

- sstate 认为 `rockchip-rkbin do_deploy` 已做过，跳过写入 → CNC 的 deploy 目录缺 `ddr-rk3588.bin`
- 旧的 deploy manifest 与新的 `MACHINE` 对不上

**本分支已做的隔离：**

1. 只保留 `rk3588-image-cnc` 与 `hd-rk3588-core-cnc`
2. deploy 目录固定为 `hd-rk3588-core-cnc/`
3. PREEMPT_RT 内嵌于 CNC machine，不依赖 RT 的 machine 文件

在本分支上持续开发 **不需要** 额外操作。若曾从 RT 切过来且 build 异常，执行一次 `scripts/clean-cnc-deploy.sh` 即可。

## 硬件参数（摘要）

| 项目 | 参数 |
|------|------|
| 处理器 | Rockchip RK3588J（4×A76 + 4×A55） |
| 内存 | 8GB LPDDR4x |
| 存储 | eMMC |
| 烧录 | USB OTG（`update.img` / RKDevTool） |
| 串口 | **115200 8N1**（`ttyFIQ0`） |

## 快速构建

```bash
cd yocto-rk3588-core
git submodule update --init --recursive
source poky/oe-init-build-env build
# local.conf 已设 MACHINE = "hd-rk3588-core-cnc"
bitbake rk3588-image-cnc
```

产物：

```
build/tmp/deploy/images/hd-rk3588-core-cnc/
├── update.img
├── fitImage / hd-rk3588-core.dtb
├── u-boot.itb / idbloader.img
└── *.ext4
```

## 登录

- 用户：`root`
- 密码：无（`debug-tweaks`）

## 项目结构

```
yocto-rk3588-core/
├── poky/                      # Yocto scarthgap
├── meta-openembedded/         # XFCE 等
├── meta-rockchip/             # Rockchip BSP
├── meta-rockchip-updateimg/   # update.img 打包
├── meta-rk3588-custom/        # CNC machine + recipes-cnc/
├── scripts/clean-cnc-deploy.sh
└── build/
```
