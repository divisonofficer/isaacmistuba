# hpBRDF

Hyperspectral Polarimetric BRDFs of Real-world Materials

## Compiling Mitsuba3 for the hpBRDF Dataset

### 1. Prepare the Mitsuba3 Source Code

First, clone the Mitsuba3 repository:

```bash
git clone -b stable --recursive https://github.com/mitsuba-renderer/mitsuba3
```

### 2. Replace measured_polarized.cpp

Next, update the `mitsuba3/src/bsdfs/measured_polarized.cpp` file (around line 158) as shown below:

```diff
        pbrdf.shape[5] == 4) {
    Throw("Invalid file structure: %s", tf->to_string());
}

- ScalarFloat wavelengths[5];
- for (size_t i = 0; i < 5; ++i) {
+ ScalarFloat *wavelengths = new ScalarFloat[wvls.shape[0]];
+ for (size_t i = 0; i < wvls.shape[0]; ++i) {
    wavelengths[i] = ScalarFloat(((uint16_t *) wvls.data)[i]);
}

m_interpolator = Interpolator(
            (ScalarFloat *) pbrdf.data,
            ScalarVector2u(4, 4),
```

Alternatively, you can copy the modified `measured_polarized.cpp` from this repository:

```bash
# On Linux / macOS
cp measured_polarized.cpp mitsuba3/src/bsdfs/measured_polarized.cpp

# On Windows (cmd)
copy measured_polarized.cpp mitsuba3\src\bsdfs\measured_polarized.cpp

# On Windows (PowerShell)
Copy-Item -Path measured_polarized.cpp -Destination mitsuba3\src\bsdfs\measured_polarized.cpp -Force
```

### 3. Compile Mitsuba3

Finally, compile Mitsuba3 by following the [official instructions](https://mitsuba.readthedocs.io/en/stable/src/developer_guide/compiling.html).

Ensure that the *_spectral_polarized* variants are enabled by editing the `mitsuba3/build/mitsuba.conf` file. For example:

```json
"enabled": [
    "scalar_rgb", "scalar_spectral_polarized", "llvm_ad_spectral_polarized"
],
```
