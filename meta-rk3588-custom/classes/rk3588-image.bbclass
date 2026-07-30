# HD-RK3588-CORE image convenience helpers.

IMAGE_POSTPROCESS_COMMAND:append = " link_latest_image;"
link_latest_image() {
    rm -rf "${TOPDIR}/latest"
    ln -sf "${DEPLOY_DIR_IMAGE}" "${TOPDIR}/latest"
}
