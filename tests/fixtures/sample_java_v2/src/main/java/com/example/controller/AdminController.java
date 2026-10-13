package com.example.controller;

import com.example.model.User;
import com.example.repository.JdbcUserRepository;

public class AdminController {
    private final JdbcUserRepository repository = new JdbcUserRepository();

    public String show(long id) {
        User user = repository.findById(id).orElse(null);
        return user == null ? "none" : user.getName();
    }
}
