# Gramocrawl - GcrawlAI Frontend

This is the frontend application for Gramocrawl, a powerful web crawling and data extraction tool. It provides a user-friendly interface to configure crawl jobs, view real-time progress, and manage extracted data.

## 🚀 Features

- *User Authentication*: Secure signup and login with OTP verification.
- *Dashboard*: Overview of crawl tasks and system status.
- *Crawl Configuration*: Easy-to-use forms to start single-page or full-site crawls.
- *Real-time Progress*: Visual feedback on crawling status via WebSockets.
- *Data Visualization*: View and export extracted data in Markdown and JSON formats.
- *Responsive Design*: Built with Bootstrap 5 for a seamless experience on any device.

## 🛠️ Technology Stack

- *Framework*: [Angular 16](https://angular.io/)
- *Styling*: [Bootstrap 5](https://getbootstrap.com/), SCSS
- *State Management*: RxJS
- *Icons*: Bootstrap Icons
- *HTTP Client*: Angular HttpClient

## 📋 Prerequisites

Before you begin, ensure you have the following installed:

- *Node.js*: v16.14.0 or higher
- *npm*: v8.3.1 or higher
- *Angular CLI*: v16.1.8 (npm install -g @angular/cli)

## ⚙️ Installation

1.  *Navigate to the frontend directory*:

    bash
    cd frontend
    

2.  *Install dependencies*:
    bash
    npm install
    

## 🔧 Configuration

The application uses environments files for configuration.

- *Development*: src/environement/environemet.ts
- *Production*: src/environement/environemet.prod.ts (if applicable)

To change the API URL, update the apiUrl property in the respective environment file.

## ▶️ Running the Application

1.  *Start the development server*:

    bash
    ng serve
    

2.  *Access the application*:
    Open your browser and navigate to http://localhost:4200/. The application will automatically reload if you change any of the source files.

## 📦 Build

To build the project for production:

bash
ng build


The build artifacts will be stored in the dist/gramocrawl directory.

## 🧪 Running Tests

- *Unit Tests*: Run ng test to execute unit tests via [Karma](https://karma-runner.github.io).
- *End-to-End Tests*: Run ng e2e to execute end-to-end tests.

## 🤝 Contributing

1.  Fork the repository.
2.  Create a new branch (git checkout -b feature/amazing-feature).
3.  Commit your changes (git commit -m 'Add some amazing feature').
4.  Push to the branch (git push origin feature/amazing-feature).
5.  Open a Pull Request.