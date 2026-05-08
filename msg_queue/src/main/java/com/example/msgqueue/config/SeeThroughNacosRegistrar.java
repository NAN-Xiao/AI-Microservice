package com.example.msgqueue.config;

import com.alibaba.nacos.api.NacosFactory;
import com.alibaba.nacos.api.exception.NacosException;
import com.alibaba.nacos.api.naming.NamingService;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

import java.net.URI;
import java.util.Properties;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

@Component
public class SeeThroughNacosRegistrar {

    private static final Logger log = LoggerFactory.getLogger(SeeThroughNacosRegistrar.class);
    private static final int REGISTER_MAX_ATTEMPTS = 5;
    private static final long REGISTER_RETRY_DELAY_SECONDS = 2L;

    private final SeeThroughProperties seeThroughProperties;
    private final ScheduledExecutorService registerExecutor = Executors.newSingleThreadScheduledExecutor(r -> {
        Thread thread = new Thread(r, "see-through-nacos-registrar");
        thread.setDaemon(true);
        return thread;
    });

    @Value("${spring.cloud.nacos.discovery.enabled:true}")
    private boolean nacosEnabled;

    @Value("${see-through.nacos-registration.enabled:true}")
    private boolean registrationEnabled;

    @Value("${see-through.nacos-registration.service-name:see-through-service}")
    private String serviceName;

    @Value("${spring.cloud.nacos.discovery.server-addr:127.0.0.1:8848}")
    private String serverAddr;

    @Value("${spring.cloud.nacos.discovery.namespace:}")
    private String namespace;

    @Value("${spring.cloud.nacos.discovery.group:DEFAULT_GROUP}")
    private String groupName;

    @Value("${spring.cloud.nacos.discovery.cluster-name:DEFAULT}")
    private String clusterName;

    @Value("${spring.cloud.nacos.discovery.username:nacos}")
    private String username;

    @Value("${spring.cloud.nacos.discovery.password:nacos}")
    private String password;

    private NamingService namingService;
    private String registeredIp;
    private int registeredPort;
    private volatile boolean shuttingDown;

    public SeeThroughNacosRegistrar(SeeThroughProperties seeThroughProperties) {
        this.seeThroughProperties = seeThroughProperties;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void register() {
        if (!nacosEnabled || !registrationEnabled) {
            log.info("SeeThrough Nacos registration disabled.");
            return;
        }

        URI uri;
        try {
            uri = URI.create(seeThroughProperties.getBaseUrl());
        } catch (IllegalArgumentException ex) {
            log.error("Invalid see-through.base-url, skip Nacos registration: {}",
                    seeThroughProperties.getBaseUrl(), ex);
            return;
        }

        String host = uri.getHost();
        int port = resolvePort(uri);
        if (host == null || host.isBlank() || port <= 0) {
            log.error("Invalid see-through.base-url host or port, skip Nacos registration: {}",
                    seeThroughProperties.getBaseUrl());
            return;
        }

        registerExecutor.execute(() -> registerWithRetry(host, port, 1));
    }

    private void registerWithRetry(String host, int port, int attempt) {
        if (shuttingDown || registeredIp != null) {
            return;
        }

        try {
            if (namingService == null) {
                namingService = NacosFactory.createNamingService(buildProperties());
            }
            namingService.registerInstance(serviceName, groupName, host, port, clusterName);
            registeredIp = host;
            registeredPort = port;
            log.info("Registered SeeThrough Nacos instance: serviceName={} group={} ip={} port={}",
                    serviceName, groupName, registeredIp, registeredPort);
        } catch (Exception ex) {
            if (attempt >= REGISTER_MAX_ATTEMPTS) {
                log.error("Failed to register SeeThrough Nacos instance after {} attempts: serviceName={} baseUrl={}",
                        attempt, serviceName, seeThroughProperties.getBaseUrl(), ex);
                return;
            }

            log.warn("Failed to register SeeThrough Nacos instance, will retry: serviceName={} baseUrl={} attempt={}/{} reason={}",
                    serviceName, seeThroughProperties.getBaseUrl(), attempt, REGISTER_MAX_ATTEMPTS, ex.getMessage());
            registerExecutor.schedule(
                    () -> registerWithRetry(host, port, attempt + 1),
                    REGISTER_RETRY_DELAY_SECONDS,
                    TimeUnit.SECONDS);
        }
    }

    @PreDestroy
    public void deregister() {
        shuttingDown = true;
        registerExecutor.shutdownNow();
        if (namingService == null || registeredIp == null || registeredPort <= 0) {
            return;
        }

        try {
            namingService.deregisterInstance(serviceName, groupName, registeredIp, registeredPort, clusterName);
            log.info("Deregistered SeeThrough Nacos instance: serviceName={} group={} ip={} port={}",
                    serviceName, groupName, registeredIp, registeredPort);
        } catch (NacosException ex) {
            log.warn("Failed to deregister SeeThrough Nacos instance: serviceName={} ip={} port={}",
                    serviceName, registeredIp, registeredPort, ex);
        }
    }

    private int resolvePort(URI uri) {
        if (uri.getPort() > 0) {
            return uri.getPort();
        }
        String scheme = uri.getScheme();
        if ("http".equalsIgnoreCase(scheme)) {
            return 80;
        }
        if ("https".equalsIgnoreCase(scheme)) {
            return 443;
        }
        return -1;
    }

    private Properties buildProperties() {
        Properties properties = new Properties();
        properties.put("serverAddr", serverAddr);
        if (!namespace.isBlank()) {
            properties.put("namespace", namespace);
        }
        if (!username.isBlank()) {
            properties.put("username", username);
        }
        if (!password.isBlank()) {
            properties.put("password", password);
        }
        return properties;
    }
}
