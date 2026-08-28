package com.jieli.jl_bt_ota.impl;

/** Exact JNI owner expected by libjl_ota_auth.so. No shrinking/obfuscation is used. */
public final class RcspAuth {
    static {
        System.loadLibrary("jl_ota_auth");
    }

    public native boolean nativeInit();

    public native byte[] getRandomAuthData();

    public native byte[] getEncryptedAuthData(byte[] input);

    public native int setLinkKey(byte[] linkKey);
}
