package com.example.msgqueue.config;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

import java.util.ArrayList;
import java.util.List;

@Validated
@ConfigurationProperties(prefix = "server")
public class ServerPortsProperties {

    private List<@Min(1) @Max(65535) Integer> additionalPorts = new ArrayList<>();

    public List<Integer> getAdditionalPorts() {
        return additionalPorts;
    }

    public void setAdditionalPorts(List<Integer> additionalPorts) {
        this.additionalPorts = additionalPorts == null ? new ArrayList<>() : new ArrayList<>(additionalPorts);
    }
}
