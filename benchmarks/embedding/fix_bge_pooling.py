"""
Fix BGE-Code-v1 GGUF pooling_type from CLS(3) to LAST_TOKEN(2).
The original GGUF has pooling_type=3 but BGE-Code-v1 needs LAST_TOKEN pooling.
"""
import os
import shutil
import struct

fname = os.path.expanduser('~/.atelier/embedding/bge-code-v1-F32.gguf')
out_path = fname + ".fixed"

# Read the GGUF and modify only the pooling_type byte
with open(fname, 'rb') as f:
    data = bytearray(f.read())

target_key = b'qwen2.pooling_type'
idx = data.find(target_key)
if idx < 0:
    print("ERROR: Could not find qwen2.pooling_type key in GGUF")
    # Print all readable keys
    pos = 4 + 4 + 8 + 8  # magic + version + tensor_count + kv_count
    while pos < min(len(data), 200000):
        # Try to find string keys
        pass
    exit(1)

key_end = idx + len(target_key)
# After key: 4 bytes type (UINT32=4), 4 bytes value
chunk = data[key_end:key_end+8]
type_val = struct.unpack('<I', chunk[:4])[0]
current_val = struct.unpack('<I', chunk[4:8])[0]
print(f"Found 'qwen2.pooling_type' at offset {idx}")
print(f"  type_enum = {type_val} (expected 4=UINT32)")
print(f"  current_value = {current_val} (3=CLS, need 2=LAST_TOKEN)")

if current_val != 2:
    struct.pack_into('<I', data, key_end + 4, 2)
    shutil.copy2(fname, fname + ".bak")
    with open(out_path, 'wb') as f:
        f.write(data)
    print(f"Fixed: changed pooling_type {current_val} -> 2")
    print(f"Written: {out_path} ({len(data)/1024/1024:.1f} MB)")
else:
    print("Already correct (pooling_type=2)")
