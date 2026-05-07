package com.example.msgqueue.service;

import org.springframework.core.io.ByteArrayResource;

public class ByteArrayMultipartFileResource extends ByteArrayResource {

    private final String filename;

    public ByteArrayMultipartFileResource(byte[] byteArray, String filename) {
        super(byteArray);
        this.filename = filename;
    }

    @Override
    public String getFilename() {
        return filename;
    }
}

