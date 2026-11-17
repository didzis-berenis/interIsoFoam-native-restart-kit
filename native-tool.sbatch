#!/bin/bash
#SBATCH --job-name=interIso-restart
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --time=04:00:00
#SBATCH --output=interIso-restart_%j.log
# Set partition, memory, time and task count for the target cluster and case.
set -eo pipefail
# Optional: load the exact OpenFOAM module provided by the cluster.
if [[ -n "${NATIVE_FOAM_MODULE:-}" ]]; then
    module load "$NATIVE_FOAM_MODULE"
fi
# Optional: verify this path before setting NATIVE_FOAM_BASH.
# Otherwise the job must inherit a working OpenFOAM environment.
if [[ -n "${NATIVE_FOAM_BASH:-}" ]]; then
    [[ -f "$NATIVE_FOAM_BASH" ]] || { echo "OpenFOAM environment script missing: $NATIVE_FOAM_BASH"; exit 1; }
    # Environment setup scripts may use nonzero statuses internally.
    if ! source "$NATIVE_FOAM_BASH"; then
        echo "Failed to load OpenFOAM environment: $NATIVE_FOAM_BASH"
        exit 1
    fi
fi
for tool in interIsoFoam foamDictionary; do
    command -v "$tool" >/dev/null || { echo "Missing $tool: load OpenFOAM or set NATIVE_FOAM_MODULE/NATIVE_FOAM_BASH"; exit 1; }
done
KIT="${NATIVE_KIT:-$SLURM_SUBMIT_DIR/interIsoFoam-native-restart-kit}"
PYTHON="${NATIVE_PYTHON:-python3}"
"$PYTHON" -c 'import sys;sys.exit(0 if sys.version_info >= (3,7) else "Python >=3.7 required")'
if [[ $# -eq 0 ]]; then
    echo 'Usage: sbatch native-tool.sbatch ACTION [native_restart.py arguments]'
    exit 2
fi
if [[ "$1" == selftest ]]; then
    shift
    "$PYTHON" "$KIT/selftest.py" "$@"
else
    "$PYTHON" "$KIT/native_restart.py" "$@"
fi
# End without additional mesh preparation or postprocessing.
