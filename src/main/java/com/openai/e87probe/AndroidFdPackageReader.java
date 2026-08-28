package com.openai.e87probe;

import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;

import java.io.Closeable;
import java.io.File;
import java.io.FileDescriptor;
import java.io.IOException;

/**
 * Android-only single-descriptor reader for the reviewed package snapshot.
 */
final class AndroidFdPackageReader {
    private AndroidFdPackageReader() {}

    static byte[] readExactly(File file, int expectedSize, int maxSize) throws IOException {
        if (file == null || maxSize <= 0
                || expectedSize <= 0 || expectedSize > maxSize) {
            throw new IOException("Unsafe expected package size");
        }

        try (OwnedFd owner = OwnedFd.open(file.getAbsolutePath())) {
            FileDescriptor fd = owner.get();
            try {
                StructStat before = Os.fstat(fd);
                if (!OsConstants.S_ISREG(before.st_mode)) {
                    throw new IOException("Package is not a regular file");
                }
                long size = before.st_size;
                if (size < 0 || size > maxSize) {
                    throw new IOException("Package exceeds hard size cap");
                }
                if (size != expectedSize) {
                    throw new IOException(
                            "Package size mismatch: expected " + expectedSize + " got " + size);
                }

                byte[] bytes = new byte[expectedSize];
                int offset = 0;
                while (offset < bytes.length) {
                    int count = Os.read(fd, bytes, offset, bytes.length - offset);
                    if (count <= 0) {
                        throw new IOException("Unexpected package EOF at byte " + offset);
                    }
                    offset += count;
                }
                byte[] extra = new byte[1];
                int extraCount = Os.read(fd, extra, 0, 1);
                if (extraCount != 0) {
                    throw new IOException("Package grew while reading");
                }

                StructStat after = Os.fstat(fd);
                if (!OsConstants.S_ISREG(after.st_mode) || after.st_size != size) {
                    throw new IOException("Package changed while reading");
                }
                return bytes;
            } catch (ErrnoException error) {
                throw new IOException("Package fstat/read failed: " + error.getMessage(), error);
            }
        }
    }

    private static final class OwnedFd implements Closeable {
        private FileDescriptor fd;

        static OwnedFd open(String path) throws IOException {
            try {
                return new OwnedFd(Os.open(
                        path,
                        OsConstants.O_RDONLY
                                | OsConstants.O_NOFOLLOW
                                | OsConstants.O_CLOEXEC,
                        0));
            } catch (ErrnoException error) {
                throw new IOException("Package open failed: " + error.getMessage(), error);
            }
        }

        private OwnedFd(FileDescriptor fd) {
            this.fd = fd;
        }

        FileDescriptor get() {
            return fd;
        }

        @Override
        public void close() throws IOException {
            FileDescriptor current = fd;
            fd = null;
            if (current == null) return;
            try {
                Os.close(current);
            } catch (ErrnoException error) {
                throw new IOException("Package close failed: " + error.getMessage(), error);
            }
        }
    }
}
