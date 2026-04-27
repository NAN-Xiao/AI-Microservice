package com.example.msgqueue.model;

public record ErrorResponse(
        String code,
        String message
) {
}

