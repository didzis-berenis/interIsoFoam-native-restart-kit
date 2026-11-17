# Complete native restart preparation for interIsoFoam

Version 1.1. Native restart snapshots for the stock **interIsoFoam** solver in the
OpenCFD/OpenFOAM.com family. The toolkit captures restart state, verifies snapshots,
and prepares continuation cases while retaining the existing solver executable.

## What is missing from an ordinary native write?

OpenFOAM already supports normal native restarts. A normal AUTO_WRITE directory is
not automatically an exact serialization of every item in the running solver.
The distinction is between **a usable continuation** and **agreement with an
uninterrupted transient under the same numerical conditions**. A writePrecision
change cannot serialize an object that is never written or never read again.

The restart inventory includes both laminar and turbulence-model state:

| State | Standard solver behaviour | Complete-restart consideration |
|---|---|---|
| `U`, `p_rgh`, phase fraction | Primary native fields read at startup | Keep all ranks, patch values, dimensions, mesh and exact time label |
| `phi` | Read if present; otherwise constructed | Preserve it; startup flux correction can still change it |
| `rho` | READ_IF_PRESENT, without AUTO_WRITE; `rho.oldTime()` is allocated | Preserve density and available time history; current alpha alone is not a generic replacement for density history |
| `rhoPhi` | NO_READ / NO_WRITE; initialized from interpolated rho and phi | Capture it and explicitly restore before the first resumed solve when seeking transient agreement |
| `p` | Reconstructed from p_rgh and hydrostatic terms, NO_READ / AUTO_WRITE | Derived for ordinary restart; this kit also restores its saved value |
| Old-time fields (`*_0`, deeper levels) | Read/write depends on allocation, read/write options, scheme and code path | Capture every allocated history level of the selected fields, not an assumed fixed list |
| `k`, `omega`, `nut` (kOmegaSST) | Model fields have their own IO behaviour | Save/read the model state and allocated histories; coefficients and boundary conditions must match |
| `uniform/time` | Native Time metadata | Preserve exact time value/name, timestep index, `deltaT` and `deltaT0` |
| Mesh | Static mesh normally in constant/polyMesh | Preserve every processor mesh and addressing. A moving/adapting mesh needs additional mesh, motion and topology state |
| Interface reconstruction | Has persistent and reconstructed internal quantities | Test the selected reconstruction algorithm; the presence of an alpha field alone is not a universal proof |
| Stateful boundaries, sources, LES, RNG | Implementation-specific | Audit serialization or restore it explicitly; a fixed RNG seed does not restore a generator after it has advanced |
| Function objects and probes | May keep running statistics or create/reopen outputs | Output history and physical solver state are separate; restarting should not truncate earlier results |
| Write scheduler | Can affect future timesteps with adjustable output | Restarting at a new startTime can change adjustable-output scheduling, even with restored fields |

Solver source references and release tags are listed in
`source-review/sources.json`. The included source excerpts retain their OpenFOAM
GPL notices; a GPL copy is included in `source-review/`.

### Adjustable output scheduling

Adaptive timesteps with `writeControl adjustable` can follow a different timestep
sequence after restart. The next-write adjustment uses elapsed time relative to
the run's start time. Changing startTime to the checkpoint shifts this phase;
restoring fields and `uniform/time` does not preserve the scheduling origin.

V1 refuses adaptive stepping with `writeControl adjustable` or
`adjustableRunTime`. It supports tested adaptive stepping with **non-adjustable**
output scheduling. If you want that arrangement, configure it in the original test
and reference from the beginning. Do not silently change the production write
schedule at restart and claim the transient is unchanged. Fully preserving the
adjustable scheduler needs an additional Time/scheduler implementation and test.

## V1 supported and unsupported scope

Admitted: static mesh (absent dynamicMeshDict, or explicitly staticFvMesh), standard
Euler ddt, deterministic inputs, isoAlpha reconstruction, laminar or standard RAS
kOmegaSST, little-endian label32 scalar64, serial or uncollated processorN layout.
Use the **same executable SHA256, OpenFOAM runtime, MPI rank count and decomposition**
for the reference and continuation. Run the supplied self-test and a short
case-specific comparison for the intended runtime and MPI configuration.

Refused/unsupported: moving meshes, AMR, backward/CrankNicolson/localEuler schemes,
LES and unreviewed RAS, per-phase turbulence configurations, MRF, fvOptions,
porosity, alternative reconstruction schemes, and adaptive adjustable output.
Some common stochastic/coded boundaries and external includes are refused too.
These checks are not a complete classifier of every custom boundary or library.
The user must still audit custom boundary/source/model/function-object state,
external tables, runtime library dependencies and any fields not in the default
inventory. Missing support does not mean those cases cannot be restarted; it means
this kit does not certify them. Do not bypass a refusal for production.

V1 intentionally does **not** provide live installation into an unrelated running
case. Preparing a fresh case avoids forcing a dictionary reread that might reopen
existing output functions. Already-running stock cases require a separate,
case-specific live-activation review.

## Toolkit safety and directory layout

All `prepare` and `prepare-resume` destinations must be **new directories**. Source
case inputs are copied, not edited. No mesh conversion, re-decomposition, field
reconstruction, cleanup or result merging is performed by the runner.

Snapshots are written separately from normal native times:

```text
CASE/.native-restart/snapshots/EXACT_LABEL/
    processor0/EXACT_LABEL/{U,p_rgh,phi,rho,rhoPhi,alpha.*,history...,uniform/time,native-ready.json}
    processor1/EXACT_LABEL/...
    SEALED.json                       # added only after offline sealing
```

A serial snapshot omits `processor0/`. Dot-prefixed folders are hidden by default
in some file browsers: enable showing hidden files.

The controller captures selected fields at a **completed timestep**, writes all
allocated history levels, synchronizes ranks, then writes per-rank receipts.
For a stop, it sets the in-memory end time to the completed timestep after the
snapshot. MPI exits normally after the snapshot completes.
`codeRead` restores saved fields and histories during function-object construction,
before the first resumed solve. This also undoes relevant startup reconstruction
of fields such as rhoPhi. The stock solver executable is not replaced.

Snapshots are binary scalar64, with 17-digit time metadata. Binary field precision
is determined by the scalar build, not the ASCII writePrecision setting. Saving
old fields at precision 17 cannot recover digits already lost in a previous
low-precision ASCII write or float32 compact export.

A snapshot directory collision is an error. Original results, logs and snapshots
are never deleted or merged. An interrupted preparation retains a
`PREPARATION_INCOMPLETE` marker. A case may be launched only once by `run`; a second
launch is refused. For another continuation, prepare another new case directory.

`seal` checks rank/field receipts, finite values and binary framing, all-rank Time
values/names/indices/deltaT/deltaT0, clean solver End and input identity, and records SHA256 hashes.
`prepare-resume` verifies those hashes and copies the snapshot into a new case.
Before solving, `run` additionally performs matching-rank typed `postProcess`
reads with an external functions-empty dictionary, and checks hashes before/after.
No binary vector fields are parsed with foamDictionary. A snapshot receipt alone
is not a successful restart acceptance test.

The tools check previous Slurm job identity/state when a run record contains a
job ID. Outside Slurm, `--confirm-stopped` is a user assertion: independently make
sure the old solver and any other writers have finished. Case locks protect kit
runs, not arbitrary external programs. A clean End is also required for sealing.

## Run the supplied self-test

Load the OpenFOAM environment and use Python >=3.7. Check the installation path
and version before running the example:

```bash
# Example installation path: adjust this to the OpenFOAM installation on your system.
source /usr/lib/openfoam/openfoam2606/etc/bashrc
KIT=/absolute/path/interIsoFoam-native-restart-kit
python3 "$KIT/selftest.py" --output /a/new/selftest-folder --ranks 2 --ras --adaptive
```

The output folder's parent must already exist. This creates copies of the installed
small interIsoFoam damBreak tutorial, generates its mesh and initial phase field,
and runs an uninterrupted baseline plus a stopped and resumed branch. It tests
Euler, kOmegaSST, two ranks, adaptive deltaT and non-adjustable output scheduling.
Without `--ras` it tests laminar; without `--adaptive` it uses fixed timesteps.
`test-result.json`, `comparison.json`, per-branch native logs, typed-reader logs and
snapshot manifests remain in the new test folder. No source tutorial is modified.
Tolerances are fixed before comparison: pointwise abs error <= 1e-12 +
1e-8*abs(reference). All primary/reference fields and common written history
levels, including patch values, are compared. Extra deep cached histories are
reported separately, not treated as missing primary state. Failure is not retried
or hidden; retain the test folder to investigate.

The comparison is a numerical regression, not independent physical validation or
proof of equality for every future state and model. Accumulated diagnostic scalars
such as cumulative continuity error are not all serialized; physical fields and
sample values are the comparison contract.

On a Slurm cluster, configure the environment and allocation for that system.
The wrapper defaults to one task and four hours, with no partition specified.
Override the partition, time, memory and task count as required. OpenFOAM may be
loaded before submission or through the optional settings below:

```bash
export NATIVE_KIT="$KIT"
# Optional: set the exact module name used by your cluster.
# export NATIVE_FOAM_MODULE="OpenFOAM/MODULE_VERSION"
# Optional: check and set the actual environment-script path.
# export NATIVE_FOAM_BASH="/path/to/OpenFOAM/etc/bashrc"
# Optional: select a Python executable if python3 is not suitable.
# export NATIVE_PYTHON="/path/to/python3"

sbatch --ntasks=2 "$KIT/native-tool.sbatch" selftest \
    --output "$PWD/native-selftest" --ranks 2 --ras --adaptive
```

The wrapper requires `interIsoFoam` and `foamDictionary` in its job environment.
The allocation's MPI task count must match the prepared case or self-test.

## Prepare a new case before starting its simulation

The source must have finalized `system`, `constant`, `0` inputs and an existing
mesh. For parallel cases, it must already have the intended processorN/constant
and processorN/0. This kit does **not** run decomposePar on an existing case.
All source inputs must remain stable while copying. Check available space first:
new case input copies plus snapshots, normal writes, histories and continuation
copies can be substantially larger than a single ordinary time directory.

```bash
python3 "$KIT/native_restart.py" prepare \
    --source /path/to/prepared-source \
    --output /path/to/NEW-case-A --ranks 64 --confirm-inputs-stable
python3 "$KIT/native_restart.py" run --case /path/to/NEW-case-A
```

Run the solver command inside a matching allocation. With the supplied HPC wrapper,
submit `prepare` (one task is enough for copying/hashing) and then submit `run`
with the task count matching `--ranks` after preparation succeeds. Do not launch the original source batch
script, which may contain destructive preprocessing.

Preparation preserves physical inputs but explicitly sets native binary,
precision 17, purgeWrite 0, runTimeModifiable true, application interIsoFoam and
startTime 0 in the **new copy**. Existing function objects are copied too, but
operate in the new directory; audit stateful function objects before admission.
An immutable-input manifest records the solver hash and all copied system,
constant and initial-field files, excluding request controls. Later changes are
refused at sealing/restart rather than silently accepted.

Optional automated test thresholds are `prepare --stop-at 0.005` or
`--checkpoint-at 0.005`. They are thresholds, not guarantees of hitting a decimal
time exactly; the first completed step at/after the threshold is used.

## Request a checkpoint, stop, or walltime deadline

For a case **prepared by this kit**, these requests create small marker files;
the solver does the writing in its existing allocation:

```bash
python3 "$KIT/native_restart.py" request --case /path/to/NEW-case-A checkpoint
python3 "$KIT/native_restart.py" request --case /path/to/NEW-case-A stop
```

Use one action as needed, not both commands blindly. Checkpoint writes a separate
snapshot and continues; stop writes a snapshot and exits cleanly. The log prints
`NATIVE_SNAPSHOT_COMPLETE reason=safeStop time=EXACT_LABEL ranks=64`, followed by
`End`. Read the complete label rather than rounding it.

An explicit deadline command is also provided:

```bash
python3 "$KIT/native_restart.py" arm-deadline \
    --case /path/to/NEW-case-A --job CURRENT_JOB_ID --margin 7200
```

It requires the exact RUNNING Slurm ID stored by this kit's runner, reads Slurm's
EndTime, and stores an epoch two hours before allocation expiry. The solver's
master rank checks the clock and broadcasts the decision. The submitting terminal
does not need to remain connected. Snapshot/field writes must fit within the margin; measure their cost.
There is no guarantee against node loss, hung timesteps or unavailable storage.
Re-arm explicitly if Slurm's allocation end changes.
There is no automatic job submission or infinite chain.

## Seal and prepare the continuation

Wait for clean solver exit and for the previous batch job to finish. If using
another batch script, it may still be running postprocessing. Confirm no other
process writes to the source. Then:

```bash
python3 "$KIT/native_restart.py" seal \
    --case /path/to/NEW-case-A --time EXACT_LABEL \
    --log /path/to/NEW-case-A/native-solver.log --confirm-stopped

python3 "$KIT/native_restart.py" prepare-resume \
    --snapshot /path/to/NEW-case-A/.native-restart/snapshots/EXACT_LABEL \
    --output /path/to/NEW-case-B --confirm-stopped

python3 "$KIT/native_restart.py" run --case /path/to/NEW-case-B
```

The last command needs matching MPI allocation. Use `sbatch` and appropriate
`--dependency=afterok:PREPARE_JOB_ID` sequencing for the preparation/launch jobs.
The new case keeps the source endTime and decomposition. It starts from the exact
checkpoint label, restores saved state before the first solve, and creates its
own `native-solver.log` and postProcessing tree. It does not append to original
logs/probes. Combine probe segments explicitly for analysis; no old files are
discarded.

If the checkpoint already reached endTime, no continuation is needed. An explicit
`prepare-resume --end-time NEW_END` may extend a finished calculation; document
that as a changed run endpoint. Optional `--stop-at` requests another planned stop.
A continuation is **not** automatically armed for its own walltime; arm it explicitly
once running. The supplied four-hour wrapper does not silently assume a two-hour
production margin.

To verify an already sealed snapshot without changing it:

```bash
python3 "$KIT/native_restart.py" verify --snapshot /path/to/snapshot/EXACT_LABEL
```

If interrupted or failed, retain the source and incomplete new directories.
Do not delete the only previous good snapshot or blindly reuse a failed run folder.

## Acceptance checklist for each real case

1. Match runtime/build, scalar precision, decomposition, model and numerical settings.
2. Audit mesh/BC/source/interface/model/RNG state; pass the kit's admission checks.
3. On a separate copy, compare uninterrupted and split/restarted runs at the same
   physical time and timestep history, with deterministic forcing.
4. Check all fields and required old levels, interface/phase volume, fluxes, probe
   transients and conservation diagnostics. Use the same MPI layout initially.
5. Check all-rank receipts, clean End, typed reads, hashes, and preservation of
   previous output. Test a missing/truncated field and confirm refusal.
6. Measure checkpoint duration and available storage; choose walltime margin from
   measurements. Keep at least two independently verified useful restart states.
7. Only then adopt the workflow for that case. A successful small laminar test is
   not acceptance for an unrelated moving-mesh LES case.

## Validation and resource requirements

`validation/RESULTS.json` records test configurations, results and coverage. Run
`selftest.py` in the intended environment before adopting the toolkit for a case.

Memory note: binary screening and numerical comparison hold individual field files
in memory; allow several times the largest rank-field size. Hashing and solver-log
tail checks are streamed/bounded. Full snapshots and continuation case copies need
additional disk space; no automatic deletion or storage-pressure manager is included.

Endpoint note: stock Time::run uses a half-timestep stopping tolerance. A final
physical time can be slightly below the requested endTime when steps do not land
on it. Compare exact recorded physical times, not only the endTime setting.
