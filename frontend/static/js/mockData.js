const cats = [
  {
    id: 1,
    name: "Luna",
    rfidTag: "A1B2C3",
    assignedBowl: 1,
    dailyTarget: 70
  },
  {
    id: 2,
    name: "Milo",
    rfidTag: "D4E5F6",
    assignedBowl: 2,
    dailyTarget: 60
  }
];

const feedingRecords = [
  {
    id: 101,
    catId: 1,
    catName: "Luna",
    startTime: "2025-05-01 08:30",
    endTime: "2025-05-01 08:35",
    intakeGrams: 22
  },
  {
    id: 102,
    catId: 2,
    catName: "Milo",
    startTime: "2025-05-01 09:10",
    endTime: "2025-05-01 09:15",
    intakeGrams: 18
  },
  {
    id: 103,
    catId: 1,
    catName: "Luna",
    startTime: "2025-05-01 13:00",
    endTime: "2025-05-01 13:06",
    intakeGrams: 25
  },
  {
    id: 104,
    catId: 2,
    catName: "Milo",
    startTime: "2025-05-01 18:20",
    endTime: "2025-05-01 18:25",
    intakeGrams: 20
  }
];

const healthAlerts = [
  {
    id: 201,
    catId: 1,
    catName: "Luna",
    level: "High",
    message: "Food intake dropped by 45% compared with the usual average.",
    createdAt: "2025-05-01 18:40",
    status: "Unresolved"
  },
  {
    id: 202,
    catId: 2,
    catName: "Milo",
    level: "Medium",
    message: "Feeding frequency is lower than normal.",
    createdAt: "2025-05-01 19:10",
    status: "Resolved"
  }
];

const deviceStatus = {
  feederOnline: true,
  lastSyncTime: "2025-05-01 19:15"
};