#!/usr/bin/env bash
# Copy the KAIST hpBRDF (SIGGRAPH Asia 2025) patched measured_polarized.cpp
# into the Mitsuba 3 source tree, then prompt the user to rebuild.
#
# The patch source must be obtained separately from KAIST:
#   https://vclab.kaist.ac.kr/siggraphasia2025p3/
# and placed at:
#   third_party/hpbrdf_patch/measured_polarized.cpp
#
# The original upstream measured_polarized.cpp is preserved as
# ``measured_polarized.cpp.upstream.bak`` so the patch can be reverted by
# copying the backup back over the source file.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATCH="${REPO_ROOT}/third_party/hpbrdf_patch/measured_polarized.cpp"
TARGET="${REPO_ROOT}/modules/mitsuba3/src/bsdfs/measured_polarized.cpp"
BACKUP="${TARGET}.upstream.bak"
BUILD_DIR="${ROBOMITUBA_MITSUBA_BUILD:-${HOME}/robomituba-build/mitsuba3}"

if [ ! -f "${PATCH}" ]; then
    echo "ERROR: hpBRDF patch not found at:"
    echo "  ${PATCH}"
    echo
    echo "Download the patched measured_polarized.cpp from KAIST:"
    echo "  https://vclab.kaist.ac.kr/siggraphasia2025p3/"
    echo "and place it at the path above."
    exit 1
fi

if [ ! -f "${TARGET}" ]; then
    echo "ERROR: upstream source not found at: ${TARGET}"
    exit 1
fi

if [ ! -f "${BACKUP}" ]; then
    cp "${TARGET}" "${BACKUP}"
    echo "Backed up upstream source -> ${BACKUP}"
fi

cp "${PATCH}" "${TARGET}"
echo "Applied hpBRDF patch:"
echo "  ${PATCH}"
echo "  -> ${TARGET}"
echo
echo "Now rebuild Mitsuba:"
echo "  cd ${BUILD_DIR}"
echo "  cmake --build . -j\$(nproc)"
echo
echo "After rebuild, restart the daemon and the .hpbrdf preview should render."
