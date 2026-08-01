SUMMARY = "RKLLM OpenAI-compatible Flask HTTP server"
DESCRIPTION = "Board-side Flask server exposing /v1/chat/completions for Qwen-Agent"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

COMPATIBLE_HOST = "aarch64.*-linux"

SRC_URI = " \
    file://flask_server.py \
    file://start_server.sh \
    file://rkllm-server.service \
"

inherit systemd

SYSTEMD_SERVICE:${PN} = "rkllm-server.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

# Model is SCP'd after flash (rkllm blob near/over 4GiB; keep out of update.img).
RDEPENDS:${PN} = " \
    python3 \
    python3-flask \
    rkllm-runtime \
"

do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
	install -d ${D}/opt/rkllm_server
	install -m 0644 ${WORKDIR}/flask_server.py ${D}/opt/rkllm_server/flask_server.py
	install -m 0755 ${WORKDIR}/start_server.sh ${D}/opt/rkllm_server/start_server.sh

	# Target path for post-flash SCP of the ~4G .rkllm
	install -d ${D}/opt/models

	install -d ${D}${systemd_system_unitdir}
	install -m 0644 ${WORKDIR}/rkllm-server.service \
		${D}${systemd_system_unitdir}/rkllm-server.service
}

FILES:${PN} = " \
    /opt/rkllm_server \
    /opt/models \
    ${systemd_system_unitdir}/rkllm-server.service \
"
