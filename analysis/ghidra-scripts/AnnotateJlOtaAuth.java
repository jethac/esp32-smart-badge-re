// Annotate the exact libjl_ota_auth.so extracted from ZRun 2.1.6.
// Validates the executable hash before making any changes.
//@category E87

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;

public class AnnotateJlOtaAuth extends GhidraScript {
    private static final String EXPECTED_SHA256 =
        "d65dd43fb8eb284b93fcbd85c7ce4e59168f3673e28c7637ed467667e4cc5c4b";

    private Address raw(long offset) {
        return currentProgram.getImageBase().add(offset);
    }

    private void renameFunction(long offset, String name, String comment) throws Exception {
        Address address = raw(offset);
        Function function = getFunctionAt(address);
        if (function == null) {
            throw new IllegalStateException("No function at " + address + " (raw +0x" +
                Long.toHexString(offset) + ")");
        }
        function.setName(name, SourceType.USER_DEFINED);
        setPlateComment(address, comment);
        createBookmark(address, "E87", name);
        println(address + " -> " + name);
    }

    private void label(long offset, String name, String comment) throws Exception {
        Address address = raw(offset);
        createLabel(address, name, true);
        setPreComment(address, comment);
        createBookmark(address, "E87", name);
        println(address + " -> " + name);
    }

    @Override
    protected void run() throws Exception {
        if (currentProgram == null) {
            throw new IllegalStateException("Open libjl_ota_auth.so in CodeBrowser first.");
        }

        String sha256 = currentProgram.getExecutableSHA256();
        if (sha256 == null || !EXPECTED_SHA256.equalsIgnoreCase(sha256)) {
            throw new IllegalStateException(
                "Refusing to annotate an unexpected program. Expected SHA-256 " +
                EXPECTED_SHA256 + ", got " + sha256);
        }

        println("Verified libjl_ota_auth.so at image base " + currentProgram.getImageBase());

        renameFunction(0x2378, "register_RcspAuth_natives",
            "FindClass(com/jieli/jl_bt_ota/impl/RcspAuth), then RegisterNatives " +
            "with four entries at raw +0x5008.");
        renameFunction(0x23dc, "jni_RcspAuth_nativeInit",
            "JNI nativeInit()Z. Stores JavaVM/global references and initializes auth state.");
        renameFunction(0x2488, "jni_RcspAuth_getRandomAuthData",
            "JNI getRandomAuthData()[B. Returns 17 bytes: 00 followed by 16 rand() bytes.");
        renameFunction(0x2594, "jni_RcspAuth_setLinkKey",
            "JNI setLinkKey([B)I. Accepts exactly 16 bytes, copies them to g_rcsp_link_key; " +
            "returns 0 on success and 3 for invalid input.");
        renameFunction(0x2638, "jni_RcspAuth_getEncryptedAuthData",
            "JNI getEncryptedAuthData([B)[B. Consumes a 17-byte 00||challenge value and " +
            "returns 01||16-byte proprietary E1 response.");
        renameFunction(0x0d4c, "rcsp_auth_e1_response_thunk",
            "Exported branch thunk for the real E1 response routine at the following address.");
        renameFunction(0x0d50, "rcsp_auth_e1_response",
            "Proprietary BLE mutual-auth response: magic6, 16-byte input, 16-byte link key, " +
            "16-byte output. This is not OTA payload decryption and is not AES.");
        renameFunction(0x12b8, "auth_expand_key_272",
            "Expands a 16-byte key into a 272-byte proprietary cipher schedule.");
        renameFunction(0x1438, "auth_block_cipher_16",
            "Transforms one 16-byte state using the 272-byte schedule and a mode argument.");

        label(0x5008, "RcspAuth_JNINativeMethods",
            "Four 24-byte AArch64 JNINativeMethod rows:\n" +
            "nativeInit ()Z -> raw +0x23dc\n" +
            "getRandomAuthData ()[B -> raw +0x2488\n" +
            "setLinkKey ([B)I -> raw +0x2594\n" +
            "getEncryptedAuthData ([B)[B -> raw +0x2638");
        label(0x5068, "g_rcsp_link_key",
            "16-byte default link key: 06 77 5F 87 91 8D D4 23 00 5D F1 D8 CF 0C 14 2B.");
        label(0x5078, "g_rcsp_magic6",
            "Six-byte E1 input constant: 11 22 33 33 22 11.");
        label(0x5080, "g_java_vm", "JavaVM pointer populated by nativeInit.");
        label(0x5088, "g_rcsp_auth_global_ref", "JNI global reference populated by nativeInit.");
        label(0x289c, "auth_schedule_seed_table", "Proprietary E1 schedule table.");
        label(0x299c, "auth_sbox", "Proprietary E1 forward substitution table.");
        label(0x2a9c, "auth_inverse_sbox", "Proprietary E1 inverse substitution table.");
        label(0x2b9c, "crc16_nibble_table", "CRC-16 nibble lookup table.");

        setPlateComment(raw(0x2748),
            "Exported JNI firmware metadata filter. Calls parse_fw_info and compares two " +
            "16-bit identifiers. No Java call site exists in the observed ZRun/Qix OTA path.");

        println("Annotation complete. Start in jni_RcspAuth_getEncryptedAuthData and press F5.");
    }
}
