package com.example.msgqueue.model;

import java.util.List;

public record SeeThroughResult(
        String filename,
        String contentType,
        String cleanupToken,
        byte[] body,
        List<String> setCookieHeaders
) {
}

