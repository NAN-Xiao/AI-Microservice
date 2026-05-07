package com.example.msgqueue.exception;

public class SeeThroughTaskException extends RuntimeException {

    private final int statusCode;

    public SeeThroughTaskException(int statusCode, String message) {
        super(message);
        this.statusCode = statusCode;
    }

    public int getStatusCode() {
        return statusCode;
    }
}

